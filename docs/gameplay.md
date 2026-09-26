# New Eridian v2 production economy

The society remains New Eridian. The production balance layer adapts the versioned recipe catalog without changing its historical source file or existing inventory quantities.

## Batch sizes

Finished goods, machines, furniture, clothing, tools, and prepared food produce one item per batch. Materials, components, seeds, and medical supplies produce bulk batches. Material water is included even though it appears in the drinks browser.

Base output is 15 when an ingredient is used by at least 20 distinct recipes or any recipe needs at least 20 units. Otherwise it is 10 when at least five recipes use it or a recipe needs five units. Other bulk items produce five. Every ingredient recipe counts once; quantities refer to the existing recipe inputs.

A matching station adds two units per station tier above Starter, capped at 20. The selected recipe keeps its own ingredients, skill requirement, and station access requirements. Alternate recipes at different benches remain distinct choices in autocomplete. If one recipe permits several stations, the best eligible unlocked station is selected. Owning or unlocking a higher station does not bypass recipe skill or personal-tier requirements.

Gathering and recipes without inputs keep their existing outputs. Rare mining still requires three successful prospecting steps per ore, and a failure grants Stone Dust. Crafting consumes inputs once per successful batch; queues record actual inventory changes. Manufacturing progression still counts batches, not individual units produced.

## Prices and sale value

Every obtainable catalog item has a Seed Industries sell price. Starter and training stock remains purchasable; newly listed finished goods are sell-only. This keeps a reason to craft and prevents a zero-price purchase from a sell-only listing.

Raw supply purchase values remain anchored to the existing economy. Manufactured appraisal uses the least expensive reachable recipe, input purchase values, and a processing allowance of 12 SC plus six SC per required game skill level. Values are divided by base output, rounded up, and floored at two SC. Input-free non-gathered products get a four-SC anchor. Alternative processing routes may have different margins. Sell value is 70 percent of appraisal rounded down, at least one SC. Purchase prices always exceed sale prices where purchases are available.

Recipe previews show batch sale proceeds, input resale value, and the difference. That difference is not profit after buying ingredients: purchased inputs cost more than their resale value. Skill progression, improved stations, and gathering your own supplies improve the practical return. Buying an item and immediately reselling it loses SC. Crafting for resale is intentional paid production work.

## Examples

| Recipe and station | Batch output | Batch sale | Input resale value |
| --- | ---: | ---: | ---: |
| Wood Planks — Carpentry Station | 15 | 15 SC | 2 SC |
| Wood Planks — Advanced Carpentry Station | 17 | 17 SC | 2 SC |
| Wood Planks — Table Saw | 19 | 19 SC | 4 SC |
| Iron Nails — Basic Anvil | 15 | 15 SC | 4 SC |
| Small Electric Motor — Electronics Workbench | 14 | 98 SC | 41 SC |
| 3D Printer — Advanced Workbench | 1 | 88 SC | 59 SC |

These are current NPC values, not forecasts of player market demand. Some alternate conversion recipes break even on ingredient resale value; previews expose that tradeoff. Table Saw planks consume two Lumber, while the two carpentry recipes consume one.

## Compatibility

No database migration, inventory conversion, or Discord command registration change is required. Existing queues resolve output using the new rules on their next successful attempt. Already completed attempts retain their original totals. The prior journal-length correction and restored Discord footer remain separate, compatible updates. Fire icons have no effect on production or pricing.
