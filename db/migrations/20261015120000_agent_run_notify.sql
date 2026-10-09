-- +goose Up
-- every change to a run or its messages wakes the API processes streaming it (server/agent_api.py, follow)
-- +goose StatementBegin
CREATE FUNCTION notify_agent_run() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'agent_runs' THEN
        PERFORM pg_notify('agent_run', NEW.id);
    ELSIF NEW.run_id IS NOT NULL THEN
        PERFORM pg_notify('agent_run', NEW.run_id);
    END IF;
    RETURN NULL;
END;
$$;
-- +goose StatementEnd
CREATE TRIGGER agent_runs_notify AFTER INSERT OR UPDATE ON agent_runs
    FOR EACH ROW EXECUTE FUNCTION notify_agent_run();
CREATE TRIGGER agent_messages_notify AFTER INSERT ON agent_messages
    FOR EACH ROW EXECUTE FUNCTION notify_agent_run();

-- +goose Down
DROP TRIGGER IF EXISTS agent_messages_notify ON agent_messages;
DROP TRIGGER IF EXISTS agent_runs_notify ON agent_runs;
DROP FUNCTION IF EXISTS notify_agent_run();
