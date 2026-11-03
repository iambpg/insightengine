# Vendor product images

These photos are the fallback used when a model has no Visio front panel and no device-type-library elevation image. Each file is a front panel cropped from the vendor's own product or datasheet page.

No separate product photo was stored for the priority models (Catalyst 2960-Plus 48TC-L, C9300-48P, FortiGate 40F, FortiGate 1200D, PA-3220, Meraki MS120-48FP). Each of those has an official Visio front panel, which is what the device page draws.

FortiGate 40F has no elevation image in the device-type library (`front_image` is unset). Its front panel comes from the Fortinet Visio stencil `FG/FWF-40/41F`, not from a fortinet.com photograph.

| Model | Result |
| --- | --- |
| FortiGate 40F | Visio stencil used. No separate fortinet.com crop stored. |
| Catalyst 8000 / cEdge packs that 403 without an archive copy | Drawn from the device-type port list until a photo is added here. |
