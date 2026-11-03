# Visio faceplate sources

Each SVG under this directory is one front or rear panel extracted from a vendor Visio stencil. `emf2svg-conv` turns the stencil's enhanced metafile into paths, so the drawing stays sharp at any size. Port connection points from the stencil, when present, are stored in the matching `.json` sidecar. Other panels get hotspots from a port-opening scan, which `ui/src/app/faceplate-calibrate` can correct.

## Downloaded directly

- Fortinet Visio stencils (Document Library / icon library zip): https://www.fortinet.com/content/dam/fortinet/assets/downloads/Fortinet%20Visio%20Stencil.zip
- Palo Alto Networks press-kit stencil (.vssx): https://www.paloaltonetworks.com/content/dam/pan/en_US/assets/pdf/corporate/panw-vssx.vssx
- Palo Alto Networks press-kit stencil (.vss): https://www.paloaltonetworks.com/content/dam/pan/en_US/assets/pdf/corporate/panw-vss.vss

## Cisco and Meraki

The stencil listing at https://www.cisco.com/c/en/us/products/visio-stencil-listing.html returns **HTTP 403 Access Denied** from this environment. The same official zip URLs were fetched from the Internet Archive snapshot of those cisco.com files:

- Catalyst 2960 (includes 2960-Plus and 2960-X): https://www.cisco.com/c/dam/assets/prod/visio/visio/products_visio_icon0900aecd80395a84.zip
- Catalyst 9000 (9200, 9300, 9400, 9500, 9600): https://www.cisco.com/c/dam/assets/prod/visio/visio/switches-catalyst-9000.zip
- Wireless (includes Catalyst 9800): https://www.cisco.com/c/dam/assets/prod/visio/visio/wireless.zip
- ISR 4000: https://www.cisco.com/c/dam/assets/prod/visio/visio/routers-isr-4000.zip
- ISR 1100: https://www.cisco.com/c/dam/assets/prod/visio/visio/routers-isr-1100.zip
- Catalyst 8300 edge: https://www.cisco.com/c/dam/assets/prod/visio/visio/catalyst-8300-v2.zip
- Cisco Meraki (`Security-Cisco Meraki`, 4 Dec 2019): https://www.cisco.com/c/dam/assets/prod/visio/visio/security-cisco-meraki.zip

https://meraki.cisco.com/product-collateral/cisco-meraki-visio-stencils/?file also returns **HTTP 403**. The 2019 Cisco pack does not include later models such as MX95 and MX105.

## Could not fetch

- Routers-Catalyst 8000: https://www.cisco.com/c/dam/assets/prod/visio/visio/routers-catalyst-8000.zip — cisco.com returns HTTP 403 and the Internet Archive has no snapshot. Those faceplates use a device-type photo or a drawn panel.
- Catalyst 8500 was not in the packs converted for this tree. Same fallback.

Device-type YAML and elevation photos come from https://github.com/netbox-community/devicetype-library (CC0). See `../library/LICENSE.txt`.
Vendor product photos, used only when both the stencil and the library photo are missing, are listed in `../vendor/SOURCES.md`.
