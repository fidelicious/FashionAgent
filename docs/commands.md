# Clawbot — Discord Command Reference

All commands are Discord slash commands. Type `/` in any channel the bot has access to and the command will appear in the autocomplete menu. Every response is **ephemeral** — only you can see it.

---

## Table of Contents

- [/health](#health)
- [/wardrobe](#wardrobe)
- [/add_item](#add_item)
- [/edit_item](#edit_item)
- [/forget_item](#forget_item)
- [/profile show](#profile-show)
- [/profile set](#profile-set)
- [/run_outfit](#run_outfit)

---

## /health

Check whether the bot and its dependencies are running correctly.

**Usage**
```
/health
```

**Parameters**
None.

**What it checks**
| Check | Failure impact |
|---|---|
| Database connection | 🔴 RED — bot cannot serve any requests |
| Database migrations up to date | 🟡 DEGRADED — possible schema drift |
| Ollama reachable | 🟡 DEGRADED — outfit suggestions and image pipeline will fail |

**Example**
```
/health
```
> ✅ **OK** — DB connected · migrations current · Ollama reachable

---

## /wardrobe

List the items currently in your wardrobe. Shows up to 25 items per call. Use the `category` filter to page through larger wardrobes. Each listed item's photo is attached (up to Discord's limit of 10 per message — the first 10 items get photos; the text list still shows all 25). Items without a stored image are listed text-only.

**Usage**
```
/wardrobe [category: <category>]
```

**Parameters**
| Parameter | Required | Description |
|---|---|---|
| `category` | Optional | Filter to a single category. See valid values below. |

**Valid categories**
| Value | What it covers |
|---|---|
| `tops` | Shirts, tops, sweaters |
| `bottoms` | Pants, jeans, skirts |
| `dresses` | Dresses, jumpsuits |
| `outerwear` | Jackets, coats, blazers |
| `footwear` | Shoes, boots |
| `accessories` | Bags, belts, hats, jewelry |
| `underlayers` | Underwear, tights, base layers |
| `activewear` | Athletic and workout clothing |

**Output format**

Each item is shown as:
```
• [12345678] Item Name — Brand (category/subcategory)
```
The `[12345678]` is the **short ID** — you need it for `/edit_item` and `/forget_item`.

**Examples**
```
/wardrobe
```
> Shows all items (up to 25).

```
/wardrobe category: tops
```
> Shows only tops.

---

## /add_item

Add a new clothing item by uploading a photo. The bot runs the image through the vision pipeline to automatically detect the category, color, formality, and season. The process takes 10–30 seconds on the NUC.

**Usage**
```
/add_item file: <photo> [name: <text>] [brand: <text>]
```

**Parameters**
| Parameter | Required | Description |
|---|---|---|
| `file` | **Required** | A photo of the item. JPG or PNG recommended. |
| `name` | Optional | A display name for the item (e.g. "Navy linen blazer"). If omitted, the bot generates one from the detected attributes. |
| `brand` | Optional | Brand name (e.g. "Uniqlo"). If omitted, the bot attempts to read it from the image via OCR. |

**What the bot detects automatically**
- Category and subcategory (e.g. tops / blouse)
- Primary and secondary colors
- Formality level (casual, smart-casual, business, formal)
- Applicable seasons
- Brand (via OCR if visible on tag or label)

**Example**
```
/add_item file: [attach photo] name: Charcoal merino crewneck brand: Uniqlo
```
> ✓ Added `[a3f2c841]` **Charcoal merino crewneck** — Uniqlo (tops/sweater)
> Category: tops · Color: charcoal · Formality: smart-casual · Seasons: fall, winter

**Tip:** If the bot gets something wrong (wrong category, color, etc.), use `/edit_item` to correct it afterward.

---

## /edit_item

Update a single field on an existing item. Use `/wardrobe` first to find the item's short ID. The confirmation reply includes the item's photo (if one is stored) so you can see what you changed.

**Usage**
```
/edit_item item_id: <id> field: <field> value: <value>
```

**Parameters**
| Parameter | Required | Description |
|---|---|---|
| `item_id` | **Required** | The short ID from `/wardrobe` — the 8-character code in brackets, e.g. `a3f2c841`. |
| `field` | **Required** | The field to update. See the full field list below. |
| `value` | **Required** | The new value. |

**Editable fields**
| Field | Type | Example values |
|---|---|---|
| `name` | Text | `"Navy linen blazer"` |
| `brand` | Text | `"Quince"` |
| `category` | Text | `tops`, `bottoms`, `dresses`, `outerwear`, `footwear`, `accessories`, `underlayers`, `activewear` |
| `subcategory` | Text | `blouse`, `cardigan`, `jeans`, `chelsea-boot` |
| `color_primary` | Text | `"charcoal"`, `"navy"`, `"ivory"` |
| `color_secondary` | Text | `"white"` |
| `pattern` | Text | `"solid"`, `"stripe"`, `"check"` |
| `fabric` | Comma-separated list | `"cotton, elastane"` |
| `fit` | Text | `"slim"`, `"relaxed"`, `"oversized"` |
| `silhouette` | Text | `"a-line"`, `"straight"`, `"fitted"` |
| `formality` | Text | `very-casual`, `casual`, `smart-casual`, `business`, `formal` |
| `seasons` | Comma-separated list | `"fall, winter"` |
| `size_on_tag` | Text | `"M"`, `"8"` |
| `size_true` | Text | `"S-M"` |
| `purchase_price_usd` | Number | `49.90` |
| `purchased_from` | Text | `"Uniqlo.com"` |
| `purchase_date` | Text | `"2025-11-01"` |
| `condition` | Text | `"new"`, `"good"`, `"fair"`, `"poor"` |
| `needs_tailoring` | Boolean | `true`, `false` |
| `tailoring_notes` | Text | `"Take in waist 1 inch"` |
| `care` | Text | `"Machine wash cold"` |
| `pairs_well_with` | Comma-separated item IDs | `"a3f2c841, b7d91f02"` |
| `avoid_pairing_with` | Comma-separated item IDs | `"cc441200"` |
| `notes` | Text | `"Runs large. Size down."` |

**Examples**
```
/edit_item item_id: a3f2c841 field: formality value: smart-casual
```
> ✓ `[a3f2c841]` `formality` → `smart-casual`

```
/edit_item item_id: a3f2c841 field: seasons value: fall, winter
```
> ✓ `[a3f2c841]` `seasons` → `['fall', 'winter']`

```
/edit_item item_id: a3f2c841 field: pairs_well_with value: b7d91f02, cc441200
```
> ✓ `[a3f2c841]` `pairs_well_with` → `['b7d91f02', 'cc441200']`

---

## /forget_item

Hide an item from outfit recommendations. This is a **soft delete** — the item is not permanently removed from the database and can be restored if needed. The confirmation reply includes the item's photo (if one is stored) so you can confirm you hid the right one.

**Usage**
```
/forget_item item_id: <id>
```

**Parameters**
| Parameter | Required | Description |
|---|---|---|
| `item_id` | **Required** | The short ID from `/wardrobe` — the 8-character code in brackets. |

**What "soft delete" means**
- The item disappears from `/wardrobe` and is excluded from all outfit suggestions.
- The underlying data and image are preserved on disk.
- Recovery requires direct database access — there is no `/restore_item` command in V1.

**Example**
```
/forget_item item_id: a3f2c841
```
> ✓ Forgot `[a3f2c841]`. It's hidden from recommendations but still in the DB.

---

## /profile show

Display your current style profile — the personal preferences the bot uses when building outfit suggestions.

**Usage**
```
/profile show
```

**Parameters**
None.

**Output**

The profile is grouped into sections: Physical, Sizing, Style, Sensitivities, Lifestyle, and Budget. Fields that have not been set yet appear as *(unset)*.

**Example**
```
/profile show
```
> **Physical**
> body_shape: hourglass · skin_tone: light · …
>
> **Style**
> favorite_colors: black, charcoal, navy, ivory, …
> jewelry_metal: silver · comfort_vs_style: 6

---

## /profile set

Update a single field in your style profile.

**Usage**
```
/profile set field: <field> value: <value>
```

**Parameters**
| Parameter | Required | Description |
|---|---|---|
| `field` | **Required** | The profile field to update. See the full list below. |
| `value` | **Required** | The new value. |

**Profile fields**

*Physical*
| Field | Type | Accepted values |
|---|---|---|
| `name` | Text | Any |
| `age_range` | Text | e.g. `"30s"` |
| `gender_expression` | Text | e.g. `"feminine"` |
| `height_cm` | Number | 50–250 |
| `weight_kg_optional` | Number | 20–300 |
| `body_shape` | Enum | `rectangle`, `hourglass`, `pear`, `apple`, `inverted-triangle`, `other` |
| `skin_tone` | Enum | `fair`, `light`, `medium`, `olive`, `tan`, `deep` |
| `skin_undertone` | Enum | `warm`, `cool`, `neutral` |
| `hair_color` | Text | e.g. `"blonde"` |
| `hair_length` | Text | e.g. `"shoulder"` |
| `hair_style_notes` | Text | e.g. `"natural waves"` |
| `eye_color` | Text | e.g. `"brown"` |
| `glasses` | Enum | `none`, `always`, `occasional` |

*Sizing*
| Field | Type | Accepted values |
|---|---|---|
| `top_size` | Text | e.g. `"S"`, `"M"` |
| `bottom_size` | Text | e.g. `"4"`, `"28"` |
| `dress_size` | Text | e.g. `"6"` |
| `shoe_size_us` | Number | 1–20 |
| `inseam_cm` | Number | 40–130 |
| `rise_pref` | Enum | `low`, `mid`, `high` |
| `bra_size` | Text | e.g. `"32D"` |
| `fit_pref_json` | Comma-separated list | e.g. `"fitted-top-relaxed-bottom, waist-definition"` |

*Style*
| Field | Type | Accepted values |
|---|---|---|
| `favorite_colors_json` | Comma-separated list | e.g. `"black, navy, ivory"` |
| `disliked_colors_json` | Comma-separated list | e.g. `"neon, pastels"` |
| `favorite_brands_json` | Comma-separated list | e.g. `"Uniqlo, Quince, Everlane"` |
| `disliked_brands_json` | Comma-separated list | e.g. `"fast-fashion"` |
| `jewelry_metal` | Enum | `gold`, `silver`, `rose`, `mixed` |
| `comfort_vs_style` | Number | 1 (pure comfort) to 10 (pure style) |

*Sensitivities*
| Field | Type | Accepted values |
|---|---|---|
| `fabric_avoid_json` | Comma-separated list | e.g. `"itchy-wool, stiff-synthetics"` |
| `dye_allergies_json` | Comma-separated list | e.g. `"synthetic-dye"` |

*Lifestyle*
| Field | Type | Accepted values |
|---|---|---|
| `city` | Text | e.g. `"Pittsburg, CA"` |
| `climate_notes` | Text | Free text description |
| `workplace_dress_code` | Text | Free text description |
| `commute_mode` | Enum | `walk`, `bike`, `car`, `transit`, `mixed` |
| `travel_frequency` | Text | e.g. `"once a quarter"` |
| `religious_cultural_notes` | Text | Free text |

*Budget*
| Field | Type | Accepted values |
|---|---|---|
| `monthly_clothing_budget_usd` | Number | 0–100000 |
| `cost_per_wear_target` | Number | 0–10000 |

**Examples**
```
/profile set field: body_shape value: hourglass
```
> ✓ Set `body_shape` to `hourglass`.

```
/profile set field: favorite_colors_json value: black, charcoal, navy, ivory, taupe
```
> ✓ Set `favorite_colors_json` to `black, charcoal, navy, ivory, taupe`.

```
/profile set field: comfort_vs_style value: 6
```
> ✓ Set `comfort_vs_style` to `6`.

## /run_outfit

Trigger today's outfit push immediately without waiting for the scheduled time. The collage is posted to your Discord channel exactly as the daily cron job would. Use this to test the pipeline, preview an outfit for tonight, or recover a missed push.

**Usage**
```
/run_outfit [occasion: <occasion>]
```

**Parameters**
| Parameter | Required | Description |
|---|---|---|
| `occasion` | Optional | Occasion to dress for. Defaults to `casual`. |

**Valid occasions**
| Value |
|---|
| `casual` |
| `smart-casual` |
| `business` |
| `formal` |

**What it does**
1. Scores all active wardrobe items for today's season + the chosen occasion.
2. Sends the top candidates to Gemma 3 1B (Ollama) for the final pick and one-sentence reason.
3. Renders a 2×2 Pillow collage and posts it to your Discord channel.
4. Replies ephemerally with the score, season, and occasion used.

**Example**
```
/run_outfit
```
> ✅ Outfit posted to channel.
>   score: `0.84` · season: `summer` · occasion: `casual`

```
/run_outfit occasion: business
```
> ✅ Outfit posted to channel.
>   score: `0.79` · season: `summer` · occasion: `business`

**Tip:** If Ollama is unreachable the LLM falls back to the top-scored candidate automatically — the command will still complete and note `(LLM fallback used)` in the reply.
