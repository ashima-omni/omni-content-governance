-- Governance questions as plain SQL, ready to run in an Omni workbook
-- once bi_governance is modeled.

-- This week's merge candidates, worst first
select doc_name_a, doc_name_b, similarity, shared_tiles
from bi_governance.dashboard_similarity
where snapshot_date = current_date and similarity >= 0.7
order by similarity desc;

-- Blast radius: most-depended-on views (query views included)
select view_name, count(distinct doc_id) as dashboards
from bi_governance.lineage
where snapshot_date = current_date
group by 1
order by 2 desc;

-- Is sprawl trending the right way?
select snapshot_date,
       count(case when verdict = 'merge_candidate' then 1 end) as merge_candidates,
       count(case when verdict = 'exact_duplicate' then 1 end) as exact_duplicates
from bi_governance.dashboard_similarity
group by 1
order by 1;

-- The unvisited long tail: archive candidates
select document, folder_path, owner_name, max(doc_views) as views, max(updated_at) as updated_at
from bi_governance.lineage
where snapshot_date = current_date
group by 1, 2, 3
having max(coalesce(doc_views, 0)) = 0
order by updated_at;
