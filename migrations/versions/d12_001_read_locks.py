"""Lock-only permission boundary for workers that may not mutate authorization records."""

from alembic import op

from migrations.safety import require_test_database

revision = "d12_001"
down_revision = "d09_001"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    schema = bind.dialect.identifier_preparer.quote_schema(
        bind.exec_driver_sql("SELECT current_schema()").scalar_one()
    )
    # Static statements only. Returns no data and cannot change a row. Explicit pg_temp
    # placement prevents temporary relation shadowing in this SECURITY DEFINER function.
    op.execute(f"""
    CREATE FUNCTION lock_read_record(kind text, a text, b text DEFAULT '', c text DEFAULT '')
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = {schema}, pg_catalog, pg_temp AS $$
    DECLARE required_table text;
    BEGIN
      required_table := CASE kind
        WHEN 'principal' THEN 'principals' WHEN 'experiment' THEN 'experiments'
        WHEN 'membership' THEN 'experiment_memberships' WHEN 'registry' THEN 'agent_registry'
        WHEN 'dataset' THEN 'datasets' WHEN 'knowledge' THEN 'knowledge_versions'
        WHEN 'analysis' THEN 'dataset_analyses' WHEN 'mcp' THEN 'mcp_tools' ELSE NULL END;
      IF required_table IS NULL THEN
        RAISE EXCEPTION 'Unsupported lock kind' USING ERRCODE='22023';
      END IF;
      IF NOT has_table_privilege(session_user,
          format('%I.%I',current_schema(),required_table),'SELECT') THEN
        RAISE EXCEPTION 'Lock access denied' USING ERRCODE='42501';
      END IF;
      CASE kind
        WHEN 'principal' THEN PERFORM id FROM principals WHERE id=a FOR SHARE;
        WHEN 'experiment' THEN PERFORM id FROM experiments WHERE id=a FOR SHARE;
        WHEN 'membership' THEN PERFORM actor_id FROM experiment_memberships
          WHERE experiment_id=a AND actor_id=b FOR SHARE;
        WHEN 'registry' THEN PERFORM ref FROM agent_registry WHERE agent_registry.kind=a
          AND ref=b FOR SHARE;
        WHEN 'dataset' THEN PERFORM id FROM datasets WHERE id=a FOR SHARE;
        WHEN 'knowledge' THEN PERFORM k.id FROM knowledge_versions k JOIN knowledge_grants g
          ON g.source_version_id=k.id WHERE k.id=a AND g.actor_id=b FOR SHARE OF k,g;
        WHEN 'analysis' THEN PERFORM x.id FROM dataset_analyses x JOIN datasets d
          ON x.dataset_id=d.id WHERE x.id=a FOR SHARE OF x,d;
        WHEN 'mcp' THEN PERFORM t.id FROM mcp_tools t JOIN mcp_connections x
          ON x.ref=t.connection_ref JOIN mcp_grants g ON g.tool_id=t.id
          WHERE t.id=a AND g.actor_id=b AND g.experiment_id=c FOR SHARE OF t,x,g;
        ELSE RAISE EXCEPTION 'Unsupported lock kind' USING ERRCODE='22023';
      END CASE;
    END $$;
    REVOKE ALL ON FUNCTION lock_read_record(text,text,text,text) FROM PUBLIC;
    CREATE FUNCTION refresh_mcp_discovery(connection text, entries jsonb)
    RETURNS SETOF text LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = {schema}, pg_catalog, pg_temp AS $$
    DECLARE entry jsonb; identity text;
    BEGIN
      PERFORM ref FROM mcp_connections WHERE ref=connection FOR UPDATE;
      UPDATE mcp_tools SET current=FALSE WHERE connection_ref=connection;
      FOR entry IN SELECT value FROM jsonb_array_elements(entries) LOOP
        INSERT INTO mcp_tools(id,connection_ref,name,spec,spec_hash)
          VALUES(entry->>'id',connection,entry->'spec'->>'name',entry->'spec',entry->>'hash')
          ON CONFLICT(connection_ref,name,spec_hash)
          DO UPDATE SET current=TRUE RETURNING id INTO identity;
        RETURN NEXT identity;
      END LOOP;
      -- Discovery can only remove authority. Existing grant scope/reviewer and
      -- revoked grants are never restored, including when an old schema returns.
      UPDATE mcp_grants SET revoked=TRUE WHERE tool_id IN
        (SELECT id FROM mcp_tools WHERE connection_ref=connection AND NOT current);
    END $$;
    REVOKE ALL ON FUNCTION refresh_mcp_discovery(text,jsonb) FROM PUBLIC;
    """)


def downgrade():
    require_test_database()
    op.execute("DROP FUNCTION refresh_mcp_discovery(text,jsonb)")
    op.execute("DROP FUNCTION lock_read_record(text,text,text,text)")
