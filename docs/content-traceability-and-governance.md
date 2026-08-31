# Content Traceability and Dashboard Governance in Omni

**A practical guide to tracing query and view usage through the Omni API, and keeping your dashboard estate under control.**

Prepared for teams administering an Omni instance. All endpoints referenced here were verified against docs.omni.co in August 2026. Calls are relative to `https://<your-org>.omniapp.co/api` and authenticated with `Authorization: Bearer $OMNI_TOKEN` (an organization API key, or a personal access token for user-scoped work).

---

## 1. Why we wrote this

Every BI deployment we have worked on follows the same arc. The first six months produce a handful of well-loved dashboards. By month eighteen there are three hundred, nobody is sure which ones still matter, and the person who built half of them has changed teams. Sprawl is rarely caused by carelessness. It is caused by the cost of finding an existing answer being higher than the cost of building a new one.

The way out is traceability. If you can answer two questions cheaply and on demand, governance stops being a policy document and becomes routine operations:

1. For any view, field, or topic in the model: which dashboards and tiles actually use it?
2. For any dashboard: which views, fields, and topics does it depend on?

Omni's REST API answers both. This guide walks through the endpoints, gives you working scripts, covers query views as a special case, and finishes with the governance standards and automation cadence we recommend running against them.

The lineage chain you can reconstruct from the API, end to end:

```
Folder > Document (dashboard/workbook) > Tile query > Topic > View > Database table
```

---

## 2. The API building blocks

Four endpoints do most of the work. Everything later in this guide is a composition of these.

### 2.1 The content census: `GET /v1/documents`

Your starting point for any audit. Lists every dashboard and workbook with ownership and usage metadata.

```bash
curl -s "https://<org>.omniapp.co/api/v1/documents?include=_count,labels&sortField=visits&sortDirection=asc&pageSize=100" \
  -H "Authorization: Bearer $OMNI_TOKEN"
```

The parameters worth knowing: `include=_count,labels` adds favorite and view counts plus labels to each record; `sortField` accepts `favorites`, `name`, `updatedAt`, and `visits`; and you can scope with `folderId`, `creatorId`, or `labels`. Paginate with `cursor` while `pageInfo.hasNextPage` is true.

Each record carries `identifier`, `name`, `type`, `hasDashboard`, `scope`, `updatedAt`, `url`, `owner`, `folder` (with its `path`), and the `_count` block. Sorting ascending by `visits` is deliberate in the example above: it puts the unvisited long tail at the top of the page, which is exactly where your archive candidates live.

The sibling endpoint `GET /v1/content` returns folders and documents together and accepts `path` globs such as `/Finance/**`, which is convenient for folder-scoped reviews.

### 2.2 What a dashboard depends on: `GET /v1/documents/{documentId}/queries`

One call per document returns every tile query in the same JSON structure the Query API executes.

```bash
curl -s "https://<org>.omniapp.co/api/v1/documents/12db1a0a/queries" \
  -H "Authorization: Bearer $OMNI_TOKEN"
```

Each entry in `queries[]` has an `id`, a `name`, a `url` deep-linking to the tile, and the `query` object itself. Inside `query`, the lineage-relevant fields are:

| Field | What it tells you |
|---|---|
| `query.table` | The base view, as `schema__viewname` |
| `query.fields[]` | Every field referenced, qualified as `view.field` |
| `query.join_paths_from_topic_name` | The topic the query runs through |
| `query.modelId` | Which model, for the Model API calls below |
| `query.filters`, `query.sorts`, `query.limit` | The full query shape, which we also hash for duplicate detection in section 5 |

This is the reverse-traceability call. It replaces clicking through every tile in the UI.

### 2.3 Who uses this view: `GET /v1/models/{modelId}/content-validator`

The most valuable endpoint in this guide, and the one most teams have not discovered. Beyond validating that content still resolves against the model, it takes `find` and `find_type` parameters and searches every document on the model for a specific element:

```bash
# Every document that queries a view
curl -s "https://<org>.omniapp.co/api/v1/models/$MODEL_ID/content-validator?find=order_items&find_type=VIEW" \
  -H "Authorization: Bearer $OMNI_TOKEN"

# Every document using a specific field (fully qualified)
curl -s "https://<org>.omniapp.co/api/v1/models/$MODEL_ID/content-validator?find=orders.status&find_type=FIELD" \
  -H "Authorization: Bearer $OMNI_TOKEN"

# Every document built on a topic
curl -s "https://<org>.omniapp.co/api/v1/models/$MODEL_ID/content-validator?find=web_analytics&find_type=TOPIC" \
  -H "Authorization: Bearer $OMNI_TOKEN"
```

Three optional parameters matter in practice. `branch_id` validates against a model branch, so you can measure the impact of a change before merging it. `include_personal_folders=true` extends the search into personal folders, where a surprising share of real usage hides. `userId` lets an org key act on behalf of a user.

The response lists each matching document with `document_id`, `name`, `folder.path`, `owner`, and a `queries_and_issues[]` array naming the specific tiles. Called without `find` after a model change, the same endpoint returns every document with broken references, which makes it your post-deployment smoke test as well.

The same API family includes a find-and-replace operation. When you rename a view or field, use it to rewrite references across all content rather than letting users rebuild dashboards by hand. Rebuilding is where a lot of sprawl is born.

### 2.4 Down to the warehouse: `GET /v1/models/{modelId}/yaml`

To complete the chain to physical tables:

```bash
# Map of all view files in the model
curl -s "https://<org>.omniapp.co/api/v1/models/$MODEL_ID/yaml" \
  -H "Authorization: Bearer $OMNI_TOKEN"

# One view's definition (fileName is case sensitive; the schema portion is uppercase)
curl -s "https://<org>.omniapp.co/api/v1/models/$MODEL_ID/yaml?fileName=PUBLIC/order_items.view" \
  -H "Authorization: Bearer $OMNI_TOKEN"
```

A view file gives you `table_name`, `schema`, and the `sql` behind each dimension and measure, so a dashboard tile traces to physical columns. Teams running dbt can close the loop from the warehouse side with the model's dbt exposures endpoint.

For a whole-instance crawl, walk `GET /v1/folders` first, then documents per folder, then queries per document. That is the pattern Omni's own data lineage integration guide describes.

---

## 3. Query views: a special case worth its own audit

A query view is what you get from **Model > Save query as view** in a workbook: a workbook query promoted into a reusable view that compiles as a CTE at run time. In the model it is a YAML file named `<name>.query.view` (for example `users_facts.query.view`), defined either with a `query:` block for point-and-click queries or a `sql:` block for SQL ones. Omni's default names follow `{base_view}_facts` for semantic queries and `sql_query_view_HH_MM` for SQL queries. Treat those timestamped auto-names in a shared model as a review flag; nobody names a durable asset `sql_query_view_14_32` on purpose.

We give query views their own section because they sprawl in two directions at once. Unpromoted ones accumulate quietly inside individual workbooks where no audit sees them. Promoted ones become silent dependencies of other people's dashboards, and deleting one breaks content you did not know existed.

### 3.1 Inventory them

Query views are just model files with a distinctive suffix, so the model YAML endpoint is the census:

```bash
curl -s "https://<org>.omniapp.co/api/v1/models/$MODEL_ID/yaml" \
  -H "Authorization: Bearer $OMNI_TOKEN" \
  | jq '[.viewNames | to_entries[] | select(.value | endswith(".query.view"))]'
```

Fetch any individual file with `?fileName=` to see its definition. The `query:` block shows which base views and fields the query view is built from, which is its upstream lineage; the `sql:` block shows the raw SQL. Note the scope: this covers query views promoted to the shared model. Workbook-local ones do not appear here, and section 3.3 shows how to catch them.

### 3.2 Which dashboards use a given query view

A promoted query view is addressed exactly like any other view, so this is the content-validator call from section 2.3:

```bash
curl -s "https://<org>.omniapp.co/api/v1/models/$MODEL_ID/content-validator?find=users_facts&find_type=VIEW&include_personal_folders=true" \
  -H "Authorization: Bearer $OMNI_TOKEN"
```

We include personal folders by default here because query-view consumers are disproportionately likely to be personal content. Run this before editing or deleting any query view. It is your blast-radius report, and it names the owners you need to talk to.

### 3.3 The usage map, orphans, and unpromoted dependencies

In the full crawl (section 4), a tile built on a query view looks like any other tile: its `query.table` is the query view's name, and query views joined into a query appear as `<query_view>.field` entries in `query.fields`. One pass over the crawl output produces the complete usage map:

```python
qv_names = {v.removesuffix(".query.view").split("/")[-1] for v in view_files
            if v.endswith(".query.view")}                     # from section 3.1

qv_usage = {}   # query view -> set of documents
for row in lineage:                                           # from section 4
    used = {row["view"]} | {f.split(".")[0] for f in row["fields"]}
    for qv in used & qv_names:
        qv_usage.setdefault(qv, set()).add(row["doc_id"])
```

Two lists fall out of the difference, and both are exactly where query-view sprawl hides. **Orphans** (`qv_names - qv_usage.keys()`) are promoted query views that no document references; they are removal candidates. **Unpromoted dependencies** are `query.table` values that match no file in the shared model at all; those are workbook-local query views that dashboards quietly depend on, and each should either be promoted so it is governed, or flagged to its owner.

---

## 4. The full traceability crawl

See `scripts/crawl.py` in this repository for the runnable version: it walks documents, extracts tile queries, and emits one lineage row per (document, tile, field) with a stable tile hash. Invert the table on `view` and you have forward traceability for every view at once. Group on `doc_id` and you have each dashboard's dependency manifest. Land the table in your warehouse on a schedule (section 6) so lineage becomes something you query in Omni itself.

One operational note: the document-queries endpoint is rate limited at roughly 60 requests per minute; the script backs off automatically.

---

## 5. Finding duplicate and near-duplicate dashboards

Because document queries come back as canonical JSON, duplicate detection is a hashing exercise rather than a judgment call. `scripts/similarity.py` is the runnable version.

Normalize each tile's `query` by dropping volatile keys (limit, sorts, presentation settings), sorting the fields, and canonicalizing filters, then hash the result. Two documents with identical tile-hash sets are exact duplicates; one of them is redundant. For near-duplicates, compute Jaccard similarity between the two documents' hash sets. In our experience anything above about 0.7 on the same topic is a merge candidate. Rank candidates using the `_count.views` and `updatedAt` data from section 2.1, keep the visited and maintained one, and archive the other.

The same tile-hash inventory has two other uses. It answers the pre-creation question in section 7 ("a tile computing this already exists on dashboard X"), and a hash recurring across many dashboards is a promotion candidate: turn the repeated query into a single query view (section 3) so there is one definition to maintain instead of a dozen copies.

---

## 6. The audit lives in Omni: warehouse tables, modeled and monitored

The scripts in sections 4 and 5 produce their answers in memory, which is fine for a one-off exercise and useless for governance. The end state we recommend is that the audit itself lives in Omni: the scripts' only job is to keep two database tables fresh, and everything else - browsing the lineage, reading duplicate scores, deciding what to merge or archive - happens in Omni against those tables, like any other analytics. "These two dashboards score 0.85, merge them" should be a tile on a dashboard, not a line in a script's log.

**Start with what Omni already gives you.** Omni ships a built-in Analytics section (Organization Admins, left navigation; it is an embedded Omni instance inside Omni). Its pre-built dashboards cover user activity and logins, content usage for workbooks and dashboards, model behavior including query execution times and usage frequency, schedule delivery rates, and AI interactions, and admins can build custom analyses on the same production topics. That covers the usage half of this guide out of the box. What it does not contain is the lineage and duplication half - tile-to-view traceability, which dashboards use a given query view, similarity scores, orphan query views - and its sharing is deliberately narrow (admin-only, no URL sharing, no Slack deliveries), so it cannot drive team-facing alerts either. The pipeline here fills exactly that gap.

The schema lives in `sql/bi_governance_ddl.sql`: a `lineage` table (one row per tile-field, with a `snapshot_date` for trends) and a `dashboard_similarity` table (pairwise Jaccard scores with a verdict column: `exact_duplicate` at 1.0, `merge_candidate` at >= 0.7). `scripts/load_warehouse.py` appends snapshots to BigQuery or Snowflake; append, don't truncate - the history is the point.

Then model it in Omni: point a model at `bi_governance`, refresh the schema (`POST /v1/models/{modelId}/refresh-schema`), and add the views and topic from `omni/` in this repository. The governance questions become the queries in `sql/governance_queries.sql`: this week's merge candidates worst first, blast radius per view, and the sprawl trend. Build the governance dashboard from these, put an alert on the merge-candidates tile, and because it is a normal topic, your AI layer can answer "which dashboards are near-duplicates right now?" in natural language against it.

---

## 7. Governance standards we recommend

**Search before you build.** Before anyone creates a dashboard, the question is whether an existing one already answers it. `GET /v1/content` filtered by label or folder, or the duplicate index from section 5, makes the check quick. Most sprawl is created in good faith by people who could not find the existing dashboard.

**One question, one dashboard.** Omni's own guidance is that three to five charts is a healthy scope, and if you need eight "relevant" charts you probably need a differently scoped dashboard, not a bigger one. And never a copy of a dashboard just to change one filter.

**Filters and access grants instead of parallel copies.** Per-region and per-team clones are the single biggest sprawl multiplier we see. One dashboard with dashboard filters, or access grants and user attributes for row-level scoping, replaces N clones with zero marginal maintenance.

**Label the lifecycle.** Use the Labels API to tag content `certified`, `draft`, or `deprecated`. Certified content lives in shared folders behind folder permissions. Build in personal folders, promote deliberately.

**Archive on evidence, not vibes.** Zero views over a quarter and a stale `updatedAt` is an archive candidate, and the API gives you both numbers plus the owner to notify. Deletion in Omni is recoverable from trash, so the loop is safe to automate.

**No model change without a blast-radius report.** Before removing or renaming a view or field, run the content-validator `find` query (section 2.3). It names the affected documents and their owners, and find-and-replace can migrate the references.

**Restrict creation in shared spaces.** Folder permissions and connection roles keep shared folders curated. Unrestricted creation belongs in personal folders, where `include_personal_folders=true` keeps it visible to audits anyway.

---

## 8. Automating it: what runs, and how often

| Job | Cadence | What it does | Output goes to |
|---|---|---|---|
| Lineage snapshot | Nightly | Run `scripts/crawl.py`; append to `bi_governance.lineage` | Warehouse, queryable in Omni |
| Broken-content check | On every model merge, plus nightly | Content-validator with no `find`; on branches, with `branch_id` before merge | CI status / #bi-admin channel |
| Duplicate index | Weekly | `scripts/similarity.py`; append scores to `bi_governance.dashboard_similarity` | Governance dashboard + weekly digest |
| Query-view audit | Weekly | Sections 3.1 and 3.3; list new orphans, unpromoted dependencies, and `sql_query_view_*` names | Weekly digest to the BI team |
| Stale-content sweep | Monthly | Zero `_count.views` and `updatedAt` older than 90 days; notify owners, apply `deprecated` label | Owner notifications |
| Archive run | Monthly, 30 days after labeling | Delete or move-to-archive anything still `deprecated` and still unvisited | Log only |
| Estate review | Quarterly | Trend the numbers: total documents, unvisited share, duplicate count, orphan query views | Leadership summary |

**Notify owners, not channels, for stale content.** "Your dashboard X has had no views in 90 days, reply to keep it" gets a response; a channel-wide list of 40 dashboards gets ignored. The 30-day grace period between labeling and archiving is what makes the sweep feel fair.

**Wire the branch check into CI.** Add the content-validator call with `branch_id` to the pull-request pipeline and fail the check when a change breaks existing content. Highest-leverage automation in the list; costs one API call.

**Make the governance dashboard the front door.** The automation's job is to keep the tables fresh so the dashboard and its merge-candidate alert stay trustworthy. (Yes, we are aware of the irony of proposing one more dashboard. Make it a good one.)

**Keep the jobs boring.** `.github/workflows/governance.yml` in this repository is the nightly runner; a service account API key with admin scope in your secrets manager; alerts only when there is something to act on. The only jobs that write anything are the label sweep and the archive run, and both act only on evidence with a human-visible grace period.

---

## 9. Quick reference

| Question | Call |
|---|---|
| What dashboards exist, who owns them, are they used? | `GET /v1/documents?include=_count,labels` |
| List all query views in a model | `GET /v1/models/{modelId}/yaml`, files ending `.query.view` |
| Which dashboards use query view Z? | `GET /v1/models/{modelId}/content-validator?find=Z&find_type=VIEW` |
| What does dashboard X depend on? | `GET /v1/documents/{id}/queries` |
| Which dashboards use view / field / topic Y? | `GET /v1/models/{modelId}/content-validator?find=Y&find_type=VIEW\|FIELD\|TOPIC` |
| What breaks if I merge this model branch? | Same endpoint, plus `branch_id` |
| Rename a field everywhere it is used | Content-validator find-and-replace |
| View to warehouse table and columns | `GET /v1/models/{modelId}/yaml?fileName=SCHEMA/view.view` |
| Full folder tree for a crawl | `GET /v1/folders`, then `GET /v1/documents?folderId=` |
| Re-run a tile's query programmatically | `POST /v1/query/run` with the `query` object from document queries |

---

## Sources

- [Document APIs: list documents](https://docs.omni.co/api/documents/list-documents.md) and [get document queries](https://docs.omni.co/api/documents/get-document-queries.md)
- [Content validator](https://docs.omni.co/api/content-validator/validate-content.md)
- [Content APIs: retrieve content](https://docs.omni.co/api/content/retrieve-content.md)
- [Configuring query views](https://docs.omni.co/modeling/query-views) and [saving queries as views](https://docs.omni.co/analyze-explore/saved-views)
- [Data lineage integration guide](https://docs.omni.co/guides/api/data-lineage-integration.md)
- [Running document queries with the Query API](https://docs.omni.co/docs/API/guides/run-document-queries)
- [Usage analytics (built-in Analytics)](https://docs.omni.co/administration/analytics)
- [Dashboarding best practices](https://docs.omni.co/guides/dashboards/dashboarding-best-practices.md)
- [Omni REST API index](https://docs.omni.co/api)
