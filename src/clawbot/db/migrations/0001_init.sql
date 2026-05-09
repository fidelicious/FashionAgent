-- =============================================================================
-- Clawbot V1 initial schema.
--
-- Conventions:
--   - Primary keys are TEXT UUIDs (generated in Python with uuid4).
--   - Timestamps are TEXT in ISO-8601 UTC ('YYYY-MM-DDTHH:MM:SSZ').
--   - Multi-valued attributes are TEXT JSON (queried via json_extract).
--   - Soft delete: deleted_at IS NULL means active.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- user_profile
--
-- Single-row table. The 'singleton' CHECK guarantees exactly one row.
-- Adding fields means a new migration; never reuse a column name.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE user_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),

    -- Identity / physical
    name                    TEXT,
    age_range               TEXT,
    gender_expression       TEXT,
    height_cm               INTEGER,
    weight_kg_optional      INTEGER,
    body_shape              TEXT,
    skin_tone               TEXT,
    skin_undertone          TEXT,
    hair_color              TEXT,
    hair_length             TEXT,
    hair_style_notes        TEXT,
    eye_color               TEXT,
    glasses                 TEXT,
    piercings_json          TEXT,
    tattoos_json            TEXT,

    -- Sizing
    top_size                TEXT,
    bottom_size             TEXT,
    dress_size              TEXT,
    shoe_size_us            REAL,
    inseam_cm               INTEGER,
    rise_pref               TEXT,
    bra_size                TEXT,
    fit_pref_json           TEXT,

    -- Style preferences
    favorite_colors_json    TEXT,
    disliked_colors_json    TEXT,
    favorite_brands_json    TEXT,
    disliked_brands_json    TEXT,
    jewelry_metal           TEXT,
    comfort_vs_style        INTEGER CHECK (comfort_vs_style BETWEEN 1 AND 10),

    -- Sensitivities
    fabric_avoid_json       TEXT,
    dye_allergies_json      TEXT,

    -- Lifestyle / context
    city                    TEXT,
    climate_notes           TEXT,
    workplace_dress_code    TEXT,
    commute_mode            TEXT,
    activity_schedule_json  TEXT,
    travel_frequency        TEXT,
    religious_cultural_notes TEXT,

    -- Budget
    monthly_clothing_budget_usd  INTEGER,
    cost_per_wear_target         INTEGER,

    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Seed the singleton row so SET commands always have a target.
INSERT INTO user_profile (id) VALUES (1);

-- ─────────────────────────────────────────────────────────────────────────────
-- wardrobe_items
--
-- The core of the system. Mostly nullable because the auto-ingest pipeline
-- fills fields incrementally and lets the user confirm later.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE wardrobe_items (
    id                       TEXT PRIMARY KEY,         -- uuid4
    category                 TEXT NOT NULL,            -- top-level (tops/bottoms/...)
    subcategory              TEXT,                     -- cardigan, ankle-boot, ...
    brand                    TEXT,
    name                     TEXT,
    color_primary            TEXT,
    color_secondary          TEXT,
    pattern                  TEXT,                     -- solid / striped / floral / ...
    fabric_json              TEXT,                     -- ["cotton","elastane"]
    fit                      TEXT,                     -- slim/regular/relaxed/oversized
    silhouette               TEXT,
    formality                TEXT,                     -- very-casual..formal
    seasons_json             TEXT,                     -- ["spring","fall"]
    size_on_tag              TEXT,
    size_true                TEXT,
    purchase_date            TEXT,
    purchase_price_usd       REAL,
    purchased_from           TEXT,
    condition                TEXT,                     -- new/good/worn/retire-soon
    needs_tailoring_bool     INTEGER NOT NULL DEFAULT 0,
    tailoring_notes          TEXT,
    care                     TEXT,                     -- dry-clean/machine/hand/wipe
    pairs_well_with_json     TEXT,                     -- ["item_id_a","item_id_b"]
    avoid_pairing_with_json  TEXT,
    wear_count               INTEGER NOT NULL DEFAULT 0,
    last_worn_date           TEXT,
    image_raw_path           TEXT,
    image_cutout_path        TEXT,
    image_final_path         TEXT,
    notes                    TEXT,

    created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    deleted_at               TEXT                       -- soft delete: NULL means active
);

-- Most-common queries: list a category, filter active items.
CREATE INDEX idx_wardrobe_items_category    ON wardrobe_items(category, deleted_at);
CREATE INDEX idx_wardrobe_items_subcategory ON wardrobe_items(subcategory, deleted_at);
CREATE INDEX idx_wardrobe_items_formality   ON wardrobe_items(formality, deleted_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- outfits + outfit_items
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE outfits (
    id                  TEXT PRIMARY KEY,
    generated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    occasion            TEXT,
    weather_summary     TEXT,
    score               REAL,
    llm_explanation     TEXT,
    collage_path        TEXT,
    user_feedback       TEXT  -- 'up' | 'down' | 'wore' | 'returned' | NULL (V2-ready)
);

CREATE TABLE outfit_items (
    outfit_id  TEXT NOT NULL REFERENCES outfits(id) ON DELETE CASCADE,
    item_id    TEXT NOT NULL REFERENCES wardrobe_items(id),
    role       TEXT NOT NULL,  -- top/bottom/outer/footwear/accessory/dress
    PRIMARY KEY (outfit_id, item_id)
);

CREATE INDEX idx_outfit_items_item ON outfit_items(item_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- recommendations
--
-- For daily push, sale alerts (V2). Decoupled from outfits because
-- recommendations can be sale alerts that aren't outfits.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE recommendations (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,       -- 'daily_outfit' | 'sale_alert' | 'gap'
    payload_json TEXT NOT NULL,
    status       TEXT NOT NULL,       -- 'queued' | 'sent' | 'acked' | 'dismissed'
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    sent_at      TEXT
);

CREATE INDEX idx_recommendations_status ON recommendations(status, created_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- jobs
--
-- Async work queue (image ingest, scrape, etc.). Polled by the worker.
-- attempts/error fields enable retry-with-backoff in jobs.py.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,    -- 'ingest_image' | 'daily_outfit' | ...
    status          TEXT NOT NULL,    -- 'queued' | 'running' | 'done' | 'failed'
    payload_json    TEXT,
    error           TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    scheduled_for   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    started_at      TEXT,
    finished_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_jobs_status_scheduled ON jobs(status, scheduled_for);
CREATE INDEX idx_jobs_kind ON jobs(kind, status);

-- ─────────────────────────────────────────────────────────────────────────────
-- audit_log
--
-- Every state change writes one row. Powers the "no silent failures" rule.
-- Append-only. Pruned by retention job (V2).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    kind    TEXT NOT NULL,            -- 'item_added' | 'profile_updated' | 'job_failed' | ...
    actor   TEXT,                     -- 'user:<discord_id>' | 'system' | 'job:<id>'
    message TEXT NOT NULL
);

CREATE INDEX idx_audit_log_ts ON audit_log(ts);

-- ─────────────────────────────────────────────────────────────────────────────
-- wardrobe_items_vec
--
-- Fashion-CLIP image embeddings (512-dim float).
--
-- The +item_id auxiliary column lets us round-trip back to wardrobe_items
-- without maintaining an integer rowid mapping. Vector search is:
--   SELECT item_id, distance
--     FROM wardrobe_items_vec
--    WHERE embedding MATCH :vec AND k = 10
-- ORDER BY distance;
-- ─────────────────────────────────────────────────────────────────────────────
CREATE VIRTUAL TABLE wardrobe_items_vec USING vec0(
    +item_id   TEXT,
    embedding  float[512]
);
