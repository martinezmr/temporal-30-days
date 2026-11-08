# Mock fixtures

Used when `LAB_MODE=mock`. Captured from the course cEOS lab (EOS 4.32.0F) unless noted.

| Path | Contents |
| --- | --- |
| `eapi/<device>.json` | eAPI JSON results, keyed by command (`show version`, `show lldp neighbors`, `show ip interface brief`) |
| `cli/show_tech/NN.txt` | Text output of the Nth command in `constants.SHOW_TECH_COMMANDS` (all captured from bos-rtr-01, except 09, which is its startup config) |
| `configs/<device>.cfg` | Running config, the same as `lab/startup-configs/` |
| `nautobot/intent.json` | Intent per device, the same values `lab/nautobot/seed.py` creates |
