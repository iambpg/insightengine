# NetBox device types

`netbox/device-types/library/` is a snapshot of [netbox-community/devicetype-library](https://github.com/netbox-community/devicetype-library) commit `6a2703f`, limited to Cisco, Fortinet, and Palo Alto Networks YAML (device types and module types). Elevation images are not included. The snapshot is in git so a server with no GitHub access can still preload NetBox.

Counts in this snapshot: 1,288 device types (Cisco 1,031, Fortinet 177, Palo Alto Networks 80) and 571 module types (557 / 8 / 6).

The Palo Alto manufacturer slug is `palo-alto`, not `palo-alto-networks`. `config/discovery/module-map.yml` and `sysobjectid-map.yml` use `palo-alto`.

## When it loads

Compose service `netbox-device-types` builds `insightengine/netbox-device-types:local` and runs once after NetBox is healthy. It reads `secrets/prometheus/netbox.token` and sends `Authorization: Bearer`. It is idempotent: a second run creates nothing. Nothing else `depends_on` this service, its NetBox dependency is `required: false`, and the image entrypoint exits 0 even when the importer does not, so a failure does not stop the rest of the stack.

On an empty NetBox the first run is on the order of three minutes. A repeat is well under a minute. The importer logs a one-line JSON summary (`device_types_created`, `module_types_created`, `templates_created`, `failures`).

NetBox copies those templates onto a device only when the device is created. `netbox-component-backfill` runs after this importer and creates any template component an existing device is missing. See [component-backfill.md](component-backfill.md).

`NETBOX_DEVICE_TYPE_VENDORS` in `.env` selects which library directories to load. The default is `Cisco,Fortinet,Palo Alto Networks`.

## Refreshing the snapshot

```bash
./scripts/refresh-device-types.sh              # commit 6a2703f
./scripts/refresh-device-types.sh <full-sha>   # another pin
docker compose build netbox-device-types
docker compose up -d netbox-device-types
```

The script sparse-checkouts only the three vendors' YAML. It needs git and network access. Commit the new `library/` and `library/SOURCE` together.
