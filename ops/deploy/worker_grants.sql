-- migration適用後と専用ロール新設時に、DB所有者として実行する。
GRANT USAGE ON SCHEMA public TO colorstats_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO colorstats_worker;
REVOKE INSERT, UPDATE, DELETE ON public.alembic_version FROM colorstats_worker;
