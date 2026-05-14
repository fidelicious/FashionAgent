"""
Text prompts for Fashion-CLIP zero-shot classification.

Constants only. Phrases are short, descriptive, and avoid overlapping
vocabulary across categories so the model has a clean distance signal.

Update the canonical taxonomy in ``fashionClaw.md`` if you add a category
here, and bump the corresponding tests in tests/vision/test_taxonomy.py.
"""

from __future__ import annotations

CATEGORY_PROMPTS: dict[str, str] = {
    "tops":        "a photo of a shirt, top, or sweater",
    "bottoms":     "a photo of pants, jeans, or a skirt",
    "dresses":     "a photo of a dress or jumpsuit",
    "outerwear":   "a photo of a jacket, coat, or blazer",
    "footwear":    "a photo of shoes or boots",
    "accessories": "a photo of a bag, belt, hat, or jewelry",
    "underlayers": "a photo of underwear, tights, or a base layer",
    "activewear":  "a photo of athletic or workout clothing",
}

FORMALITY_PROMPTS: dict[str, str] = {
    "very-casual":  "very casual loungewear or pajamas",
    "casual":       "casual everyday clothing",
    "smart-casual": "smart casual office-friendly clothing",
    "business":     "business or professional attire",
    "formal":       "formal evening wear or a suit",
}

SEASON_PROMPTS: dict[str, str] = {
    "spring": "lightweight clothing for spring weather",
    "summer": "lightweight clothing for hot summer weather",
    "fall":   "layered clothing for cool fall weather",
    "winter": "heavy clothing for cold winter weather",
}

# Per-category subcategory prompts. Picked up by classify.zero_shot only
# after the top-level category is decided, so the search space stays small.
SUBCATEGORY_PROMPTS: dict[str, dict[str, str]] = {
    "tops": {
        "t-shirt":    "a plain t-shirt",
        "tank":       "a tank top or sleeveless shirt",
        "blouse":     "a blouse",
        "button-down": "a button-down shirt",
        "sweater":    "a sweater or pullover",
        "cardigan":   "a cardigan",
        "turtleneck": "a turtleneck",
        "polo":       "a polo shirt",
        "henley":     "a henley shirt",
        "sweatshirt": "a sweatshirt",
        "hoodie":     "a hoodie",
        "crop-top":   "a crop top",
        "bodysuit":   "a bodysuit",
    },
    "bottoms": {
        "jeans":      "blue jeans",
        "trousers":   "dress trousers",
        "chinos":     "chinos or khaki pants",
        "leggings":   "leggings",
        "shorts":     "shorts",
        "mini-skirt": "a mini skirt",
        "midi-skirt": "a midi skirt",
        "maxi-skirt": "a maxi skirt",
        "culottes":   "culottes",
    },
    "dresses": {
        "mini-dress":  "a mini dress",
        "midi-dress":  "a midi dress",
        "maxi-dress":  "a maxi dress",
        "jumpsuit":    "a jumpsuit",
        "romper":      "a romper",
    },
    "outerwear": {
        "cardigan":       "a heavy cardigan worn as outerwear",
        "blazer":         "a blazer",
        "denim-jacket":   "a denim jacket",
        "leather-jacket": "a leather jacket",
        "coat":           "a long coat",
        "parka":          "a parka",
        "vest":           "a vest",
        "trench":         "a trench coat",
        "puffer":         "a puffer jacket",
    },
    "footwear": {
        "sneakers":    "sneakers",
        "loafers":     "loafers",
        "ankle-boot":  "ankle boots",
        "knee-boot":   "knee-high boots",
        "heels":       "high heels",
        "flats":       "ballet flats",
        "sandals":     "sandals",
        "mules":       "mules",
        "slides":      "slides",
    },
    "accessories": {
        "belt":       "a belt",
        "handbag":    "a handbag",
        "tote":       "a tote bag",
        "crossbody":  "a crossbody bag",
        "scarf":      "a scarf",
        "hat":        "a hat",
        "jewelry":    "jewelry",
        "sunglasses": "sunglasses",
        "watch":      "a wristwatch",
    },
    "underlayers": {
        "bra":        "a bra",
        "slip":       "a slip",
        "base-layer": "a base layer or thermal",
        "tights":     "tights",
        "socks":      "socks",
    },
    "activewear": {
        "sports-bra": "a sports bra",
        "leggings":   "athletic leggings",
        "shorts":     "athletic shorts",
        "top":        "an athletic top",
    },
}
