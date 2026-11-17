# Ratewise input form - design notes

File: `prototype/index.html` (single file, HTML + CSS + vanilla JS, open it in a browser).

## Decisions
- One standardized form, 4 sections (A Shipment, B Items, C Accessorials, D Insurance). LTL only.
- "Get Rates" only validates, builds the standard JSON payload and shows it. Results table is MOCK.
- Own validation (`novalidate`): inline message per field + a summary box; fields get `aria-invalid`.
- Items are cards (not a wide table) so they work on phones. Event delegation handles add/remove.
- Weight is the TOTAL weight of an item row (all units), not per unit.
- Class hint: density = weight / cubic ft, mapped through a simplified density table. It only suggests; user picks.
- Linear feet is a rough estimate: floor area / 96 in; stackable counts half.
- Accessorials split into Pickup and Delivery with unique keys, so mapping to portals is 1 key -> 1 portal name.
- ZIP autofill uses 8 hard-coded sample ZIPs (fake).

## Standardized field names (JSON)
- Top: `mode`, `shipDate`, `origin{country,zip,city,state}`, `destination{...}`, `items[]`, `totals`, `accessorials`, `insurance`
- Item: `handlingUnit, units, pieces, length, width, height, weight, freightClass, nmfc, description, stackable, hazmat`
- Totals: `totalUnits, totalWeightLb, linearFeetEstimate`
- Accessorials: `residentialPickup, liftgatePickup, limitedAccessPickup, insidePickup, residentialDelivery, liftgateDelivery, limitedAccessDelivery, insideDelivery, appointmentDelivery, notifyConsignee`
- Insurance: `enabled, declaredValueUsd`
- Units: inches, pounds, USD, dates ISO `YYYY-MM-DD`.

## Open questions
- Is weight per unit or per row in each portal? (Mapper may need to convert.)
- Does each portal accept the same handling unit list and class values (e.g. 77.5, 92.5)?
- Do portals need street address / location type (business, residential, port) beyond ZIP?
- Should "Hazmat" collect UN number / hazard class? Needed by most carriers.
- Real ZIP lookup source (API or offline table)? Non-US ZIP formats (CA postal codes)?
- Speedship is small package: separate form later? (excluded here).
- Which accessorials are missing (e.g. Construction Site, Trade Show, Sort/Segregate)?
