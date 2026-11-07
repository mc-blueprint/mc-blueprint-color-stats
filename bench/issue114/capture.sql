BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH images AS (
 SELECT a.subject_id, lower(trim(coalesce(a.quality->>'author',s.author,''))) AS author,
 coalesce(nullif(a.search_provider,''),s.site) AS source,
 CASE WHEN a.search_parameters ? 'collection_bias'
 THEN a.search_parameters->'collection_bias'->>'region' ELSE u.location END AS region,
 (CASE WHEN a.search_parameters ? 'collection_bias'
 THEN a.search_parameters->'collection_bias'->'intended_attributes'
 ELSE coalesce(u.scene_attributes,'{}'::jsonb) || jsonb_build_object('domain',u.domain,'region',u.location,'era',u.era) END)
 || a.scene_attributes AS attributes
 FROM asset a JOIN source s ON s.id=a.source_id LEFT JOIN subject u ON u.id=a.subject_id
), rows AS (
 SELECT *, false AS pending FROM images
 UNION ALL SELECT subject_id,author,source,region,attributes,true
 FROM collection_reservation WHERE asset_id IS NULL
), groups AS (
 SELECT attributes,source,pending,count(*) AS count FROM rows GROUP BY 1,2,3
), subjects AS (
 SELECT CASE WHEN attributes->>'domain'='real_building' THEN
 jsonb_build_object('domain',attributes->'domain','style',attributes->'style',
 'building_type',attributes->'building_type','region',attributes->'region','era',attributes->'era')
 ELSE jsonb_build_object('domain',attributes->'domain','biome_like',attributes->'biome_like',
 'season',attributes->'season','time_of_day',attributes->'time_of_day') END AS attributes,
 count(DISTINCT subject_id) AS subjects FROM images GROUP BY 1
)
SELECT json_build_object(
 'captured_at',CURRENT_TIMESTAMP,'transaction_read_only',current_setting('transaction_read_only'),
 'isolation',current_setting('transaction_isolation'),
 'asset_count',(SELECT count(*) FROM images),
 'pending_count',(SELECT count(*) FROM rows WHERE pending),
 'groups',(SELECT json_agg(groups) FROM groups),
 'subjects',(SELECT json_agg(t) FROM subjects t),
 'regions',(SELECT json_object_agg(region,n) FROM (SELECT region,count(*) n FROM rows WHERE region IN ('japan','europe','north_america','west_asia','east_asia') GROUP BY region)t),
 'max_region_images',(SELECT max(n) FROM (SELECT count(*) n FROM rows WHERE region IS NOT NULL GROUP BY region)t),
 'origin_sites',(SELECT json_object_agg(site,n) FROM (SELECT s.site,count(*) n FROM asset a JOIN source s ON a.source_id=s.id GROUP BY s.site)t),
 'max_author_images',(SELECT max(n) FROM (SELECT count(*) n FROM rows WHERE author<>'' GROUP BY author) t),
 'collect_jobs',(SELECT json_object_agg(status,n) FROM (SELECT status,count(*) n FROM job WHERE stage='collect' GROUP BY status)t),
 'alembic',(SELECT version_num FROM alembic_version));
COMMIT;
