# NetBox regions

`netbox/regions/regions.yaml` is the region tree loaded into NetBox (`dcim.region`) so a site can be placed in Africa down to a country or a first-level province. The file is in git. A server does not need network access to load it.

The tree is Africa, then a sub-region, then a country, then that country's first-level province or region. West Africa stops at the country. Slugs are unique. A subdivision slug is the ISO 3166-1 alpha-2 code, a hyphen, and the name (`za-gauteng`). The description holds the ISO 3166 code (`ISO 3166-2: ZA-GP` or `ISO 3166-1 alpha-2: ZA`). Africa and the five sub-regions are geographic groupings and do not have an ISO 3166 code.

`scripts/seed-netbox.sh` still creates the client tenant and the client root region from `CLIENT_SLUG`. That region is a separate root. Do not use `africa`, a sub-region slug, or a two-letter country slug as `CLIENT_SLUG`: the loader matches on slug and will rename that region and set its parent.

## When it loads

Compose service `netbox-regions` builds `insightengine/netbox-regions:local` and runs once after NetBox is healthy. It reads `secrets/prometheus/netbox.token` and sends `Authorization: Bearer` for a NetBox 4.6 v2 token. It is idempotent. A second run against an unchanged database creates nothing and updates nothing.

Nothing else `depends_on` this service. Its NetBox dependency is `required: false`, and the image entrypoint exits 0 even when the importer does not, so a failure does not stop the rest of the stack. The same rules apply to `netbox-device-types`.

Match key is the slug.

- Missing slug: create the name, slug, parent, and description.
- Existing slug: update the name and the parent when they differ. The description, comments, tags, and any other field are left as they are.
- A region that is not in the file is not deleted.

```bash
docker compose build netbox-regions
docker compose up -d --no-deps netbox-regions
```

The importer logs a one-line JSON summary (`regions_created`, `regions_updated`, `regions_unchanged`, `failures`).

## Counts

644 regions: Africa, 5 sub-regions, 54 countries, 584 subdivisions.

| Sub-region | Country | Slug | Subdivisions |
|---|---|---|---|
| North Africa | Egypt | eg | 27 governorates |
| North Africa | Libya | ly | 22 popularates |
| North Africa | Tunisia | tn | 24 governorates |
| North Africa | Algeria | dz | 58 provinces |
| North Africa | Morocco | ma | 12 regions |
| North Africa | Sudan | sd | 18 states |
| West Africa | Nigeria | ng | 0 (country only) |
| West Africa | Ghana | gh | 0 |
| West Africa | Senegal | sn | 0 |
| West Africa | Côte d'Ivoire | ci | 0 |
| West Africa | Mali | ml | 0 |
| West Africa | Niger | ne | 0 |
| West Africa | Burkina Faso | bf | 0 |
| West Africa | Guinea | gn | 0 |
| West Africa | Benin | bj | 0 |
| West Africa | Togo | tg | 0 |
| West Africa | Sierra Leone | sl | 0 |
| West Africa | Liberia | lr | 0 |
| West Africa | Mauritania | mr | 0 |
| West Africa | The Gambia | gm | 0 |
| West Africa | Cabo Verde | cv | 0 |
| West Africa | Guinea-Bissau | gw | 0 |
| East Africa | Kenya | ke | 47 counties |
| East Africa | Tanzania | tz | 31 regions |
| East Africa | Uganda | ug | 4 regions |
| East Africa | Ethiopia | et | 13 |
| East Africa | Somalia | so | 18 regions |
| East Africa | Rwanda | rw | 5 |
| East Africa | Burundi | bi | 18 provinces |
| East Africa | South Sudan | ss | 10 states |
| East Africa | Djibouti | dj | 6 |
| East Africa | Eritrea | er | 6 regions |
| East Africa | Madagascar | mg | 6 provinces |
| East Africa | Mauritius | mu | 12 |
| East Africa | Seychelles | sc | 27 districts |
| East Africa | Comoros | km | 3 islands |
| Central Africa | Democratic Republic of the Congo | cd | 26 |
| Central Africa | Republic of the Congo | cg | 12 departments |
| Central Africa | Cameroon | cm | 10 regions |
| Central Africa | Angola | ao | 18 provinces |
| Central Africa | Central African Republic | cf | 17 |
| Central Africa | Gabon | ga | 9 provinces |
| Central Africa | Chad | td | 23 provinces |
| Central Africa | Equatorial Guinea | gq | 8 provinces |
| Central Africa | São Tomé and Príncipe | st | 7 |
| Southern Africa | South Africa | za | 9 provinces |
| Southern Africa | Zimbabwe | zw | 10 provinces |
| Southern Africa | Zambia | zm | 10 provinces |
| Southern Africa | Namibia | na | 14 regions |
| Southern Africa | Botswana | bw | 16 |
| Southern Africa | Mozambique | mz | 11 |
| Southern Africa | Lesotho | ls | 10 districts |
| Southern Africa | Eswatini | sz | 4 regions |
| Southern Africa | Malawi | mw | 3 regions |

South Africa's nine provinces are Eastern Cape, Free State, Gauteng (`za-gauteng`, `ZA-GP`), KwaZulu-Natal, Limpopo, Mpumalanga, North West, Northern Cape, and Western Cape.

## Choices

Codes and default names come from the ISO 3166-2 list shipped in pycountry 26.2.16 (Debian iso-codes). A subdivision is included when ISO 3166-2 lists it with no parent, except where this section says otherwise. West Africa is countries only, including where ISO has states (Nigeria has 37).

- Algeria: all 58 ISO provinces, including the ten added after the original 48. North Africa uses every ISO first-level unit even though 58 is past the "about 50" cutoff used for very fine East African lists.
- Morocco: the 12 regions. The 75 prefectures and provinces have parents in ISO 3166-2 and are not loaded. `L'Oriental` is stored as Oriental. The Western Sahara notes `(EH)` and `(EH-partial)` are not part of the name.
- Egypt, Libya, and Eritrea: the ISO names are Arabic romanizations. The file uses the English names for the same codes (Cairo is `EG-C`, Tripoli is `LY-TB`, Southern Red Sea is `ER-DK`).
- Kenya: all 47 counties.
- Uganda: the 4 geographical regions (`UG-C`, `UG-E`, `UG-N`, `UG-W`), not the 134 districts.
- Seychelles: all 27 ISO districts. That is under the cutoff of about 50, so the districts are loaded instead of a coarser grouping.
- Ethiopia: the 13 ISO units (11 regional states and Addis Ababa and Dire Dawa). Sidama and Southwest Ethiopia are included. Central Ethiopia and South Ethiopia, split from SNNPR in 2023, are not separate codes in this snapshot, so SNNPR remains one region (`ET-SN`). Display names Amhara, Benishangul-Gumuz, Gambela, Harari, Southwest Ethiopia, and Tigray replace the ISO spellings Amara, Benshangul-Gumaz, Gambela Peoples, Harari People, Southwest Ethiopia Peoples, and Tigrai.
- Madagascar: the 6 ISO provinces, not the 23 regions used administratively since 2009. Those regions are not the ISO first-level list.
- Malawi: the 3 regions, not the 28 districts.
- Botswana: 10 districts plus the 6 cities and towns ISO lists at the same level (Francistown, Gaborone, Jwaneng, Lobatse, Selibe Phikwe, Sowa Town). 16 in total.
- Mozambique: 10 provinces plus Maputo city, which ISO types as a city (`MZ-MPM`). The province stays `mz-maputo` (`MZ-L`). The city is Maputo City, `mz-maputo-city`, so the slugs do not clash. That is the 11 the catalog asks for.
- Equatorial Guinea: ISO's first level is two regions (Continental and Insular) with eight provinces under them. The file loads the eight provinces directly under the country so a site can be placed on Bioko, Annobon, or the mainland. The two regions are not loaded.
- São Tomé and Príncipe: 6 districts plus the autonomous region of Príncipe.
- Central African Republic: 14 prefectures, 2 economic prefectures, and Bangui. 17 ISO first-level units.
- South Sudan: the 10 states in the current ISO list, not the former 32.
- Namibia: `NA-KA` is stored as Karas. The ISO name is `//Karas`.
- Angola: the 18 ISO provinces. Icolo e Bengo and Moxico Leste are not codes in this snapshot.
- Cabo Verde is the ISO 3166-1 short name for Cape Verde (`CV`). Côte d'Ivoire is stored under that official name (`CI`), not "Ivory Coast".
