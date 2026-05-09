# Clawbot Project Blueprint



## Purpose

Build a local-only personal fashion assistant that:

* understands wardrobe
* learns style preferences
* recommends outfits
* watches favorite stores
* sends useful alerts
* improves from feedback

The goal is:

**smart stylist assistant**

Not:

**autonomous shopping bot**

---

# Core Stack

## Hardware

* Intel NUC
Architecture:                x86_64
  CPU op-mode(s):            32-bit, 64-bit
  Address sizes:             36 bits physical, 48 bits virtual
  Byte Order:                Little Endian
CPU(s):                      4
  On-line CPU(s) list:       0-3
Vendor ID:                   GenuineIntel
  Model name:                Intel(R) Core(TM) i5-3427U CPU @ 1.80GHz
    CPU family:              6
    Model:                   58
    Thread(s) per core:      2
    Core(s) per socket:      2
    Socket(s):               1
    Stepping:                9
    CPU(s) scaling MHz:      37%
    CPU max MHz:             2800.0000
    CPU min MHz:             800.0000
    BogoMIPS:                4589.99
    Flags:                   fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush dts acpi mmx fxsr sse sse2 ss ht tm pbe syscall nx rdtscp lm constant_tsc arch_perfmon pebs bts
                              rep_good nopl xtopology nonstop_tsc cpuid aperfmperf pni pclmulqdq dtes64 monitor ds_cpl vmx smx est tm2 ssse3 cx16 xtpr pdcm pcid sse4_1 sse4_2 x2apic popcnt tsc_deadline_ti
                             mer aes xsave avx f16c rdrand lahf_lm cpuid_fault epb pti ssbd ibrs ibpb stibp tpr_shadow flexpriority ept vpid fsgsbase smep erms xsaveopt dtherm ida arat pln pts vnmi md_cle
                             ar flush_l1d
Virtualization features:
  Virtualization:            VT-x
Caches (sum of all):
  L1d:                       64 KiB (2 instances)
  L1i:                       64 KiB (2 instances)
  L2:                        512 KiB (2 instances)
  L3:                        3 MiB (1 instance)
NUMA:
  NUMA node(s):              1
  NUMA node0 CPU(s):         0-3
Vulnerabilities:
  Gather data sampling:      Not affected
  Indirect target selection: Not affected
  Itlb multihit:             KVM: Mitigation: Split huge pages
  L1tf:                      Mitigation; PTE Inversion; VMX conditional cache flushes, SMT vulnerable
  Mds:                       Mitigation; Clear CPU buffers; SMT vulnerable
  Meltdown:                  Mitigation; PTI
  Mmio stale data:           Unknown: No mitigations
  Reg file data sampling:    Not affected
  Retbleed:                  Not affected
  Spec rstack overflow:      Not affected
  Spec store bypass:         Mitigation; Speculative Store Bypass disabled via prctl
  Spectre v1:                Mitigation; usercopy/swapgs barriers and __user pointer sanitization
  Spectre v2:                Mitigation; Retpolines; IBPB conditional; IBRS_FW; STIBP conditional; RSB filling; PBRSB-eIBRS Not affected; BHI Not affected
  Srbds:                     Vulnerable: No microcode
  Tsa:                       Not affected
  Tsx async abort:           Not affected
  Vmscape:                   Mitigation; IBPB before exit to userspace

## OS

* PRETTY_NAME="Debian GNU/Linux 13 (trixie)"

## Main Language

* Python

## Containers

Use Docker from day one.

Containers:

* openclaw
* ollama
* chromadb
* open-webui
* playwright
* discord-bot
* api-service

---

# Models

## Main model

 running:

* Gemma 3 4B

## Embeddings

* nomic-embed-text

## Vision

* OpenCLIP
* MMFashion

---

# Main Components

## 1) Memory

Stores:

* measurements
* sizing
* inseam / rise
* fit preferences
* favorite colors
* disliked colors
* preferred brands
* disliked brands
* office dress expectations
* budget

---

## 2) Wardrobe System

Tracks:

* tops
* pants
* jackets
* shoes
* accessories

Each item stores:

* photo
* category
* color
* fit
* silhouette
* fabric
* season
* formality
* wear count
* last worn
* notes

---

## 3) Outfit Builder

Generates:

* office outfits
* weather outfits
* travel outfits
* capsule outfits
* seasonal transition outfits

---

## 4) Research Layer

Monitors:

Retailers:

* COS
* Everlane
* Quince
* Sezane
* Madewell
* Theory
* Aritzia
* Banana Republic
* Uniqlo
* J.Crew
* Nordstrom

Editorial:

* Who What Wear
* Vogue
* The Cut
* Coveteur

Community:

* Reddit fashion communities
* Pinterest inspiration

Focus:

**California smart casual office wear**

---

## 5) Recommendation Engine

Score formula:

```text id="m7ejii"
style_match = 35
compatibility = 25
season = 15
office = 15
budget = 10
duplicate_penalty = -25
```

Highest score wins.

Only strong recommendations are sent.

---

## 6) Learning Loop

Bot learns from:

* thumbs up
* thumbs down
* purchased
* ignored
* favorite
* returned

Future recommendations improve.

---

## 7) Notifications

Platform:

Discord

Send:

* sale alerts
* restocks
* outfit suggestions
* wardrobe gaps
* weekly digest
* monthly report

---

# Storage Layout

Single root folder:

```text id="rlzv91"
/clawbot
    /docker
    /config
    /db
    /images
        /raw
        /processed
        /cutouts
        /final
        /products
        /outfits
    /inbox
        /screenshots
        /email
    /logs
    /models
    /scripts
    /backups
```

Internal SSD storage.

Backup plan later.

---

# Database

SQLite main DB.

Tables:

* user_profile
* wardrobe_items
* recommendations
* outfits
* outfit_items
* feedback
* scrape_sources
* jobs

Vector storage:

ChromaDB

Stores:

* clothing embeddings
* recommendation embeddings
* similarity search

---

# Ingestion

Supports:

## Automatic

### Screenshot folder

```text id="p3ikm5"
/clawbot/inbox/screenshots/
```

Drop image in folder → auto process.

Examples:

* retailer screenshot
* Pinterest screenshot
* inspiration image
* product screenshot

---

### Email folder

```text id="w4e7xf"
/clawbot/inbox/email/
```

Parse:

* item
* brand
* price
* purchase date

Auto add history.

---

## Manual

Discord upload:

```text id="tkd0ii"
/add_item
```

---

## Edit Existing

Discord:

```text id="qcf8j0"
/edit_item <id>
```

---

# Image Pipeline

Flow:

```text id="7mqn8j"
input
→ save raw
→ normalize
→ remove background
→ analyze clothing
→ generate embedding
→ confidence check
→ user approve/edit
→ save final
→ write DB row
```

Extract:

* category
* color
* pattern
* texture
* sleeve length
* silhouette
* formality
* season

---

# Scraping

Tool:

Playwright

Start:

**weekly**

Initial scrape targets:

* sales
* new arrivals
* seasonal changes

Frequency editable later.

---

# Scheduling

Config file:

```yaml id="g3g6yq"
scrape:
  weekly: sunday 2:00

digest:
  weekly: monday 8:00

daily_outfit:
  daily: 7:00

monthly_report:
  monthly: day 1 9:00
```

Editable.

---

# Failure Handling

If model unavailable:

* queue job

If Discord unavailable:

* retry later

If scrape fails:

* log failure
* retry later

If disk usage high:

* clear cache

No silent failures.

---

# API Layer

Use .

Architecture:

```text id="i7g1xa"
Discord
Open WebUI
Scheduler
Automation
      ↓
   FastAPI
      ↓
 Services
      ↓
SQLite
ChromaDB
Ollama
```

Keeps system organized.

---

# Config

Single YAML config.

Example:

```yaml id="3v5x5e"
model: gemma3:4b
embedding_model: nomic-embed-text

db_path: /clawbot/db
image_path: /clawbot/images

discord_enabled: true
notifications_enabled: true
```

No hardcoding.

---

# Build Phases

## V1

Must have:

* profile memory
* wardrobe DB
* auto ingestion
* manual upload
* editing existing items
* outfit suggestions
* Discord alerts
* scrape 3 stores
* feedback learning

---

## V2

Add:

* stronger vision
* compatibility analysis
* wardrobe gap analysis
* better scoring
* style clustering

---

## V3

Add:

* seasonal planning
* event integration
* weather integration
* fit prediction
* advanced personalization

---

# Build Rule

Keep everything:

**simple**
**local**
**editable**
**modular**
**low maintenance**