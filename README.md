# Self-Hosted Homelab & Hybrid AI Architecture

> Turning a repurposed laptop into a 24/7 Ubuntu server with network-wide DNS filtering, zero-exposed-port internal HTTPS, real-time observability & Telegram alerting, automated encrypted offsite backups, and on-demand RTX 3080 GPU offloading via Wake-on-LAN.

[![OS](https://img.shields.io/badge/Ubuntu-26.04_LTS-E95420?style=flat-square&logo=ubuntu&logoColor=white)](https://ubuntu.com/)
[![Docker](https://img.shields.io/badge/Docker-13_Containers-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![Caddy](https://img.shields.io/badge/TLS-Caddy_DNS--01_HTTPS-1F88C0?style=flat-square&logo=caddy&logoColor=white)](https://caddyserver.com/)
[![Tailscale](https://img.shields.io/badge/VPN-Tailscale_WireGuard-4B32C3?style=flat-square&logo=tailscale&logoColor=white)](https://tailscale.com/)
[![Backups](https://img.shields.io/badge/Backups-Restic_%2B_Rclone_AES--256-2EA44F?style=flat-square)](https://restic.net/)
[![Local AI](https://img.shields.io/badge/Local_AI-Ollama_%2B_Open_WebUI-000000?style=flat-square)](https://ollama.com/)

---

## Why I Built This

Instead of paying for multiple SaaS subscriptions or leaving a power-hungry desktop running 24/7, I designed a **two-tier hybrid homelab**:

1. **Always-On Low-Power Core (`homeserver`):** A repurposed ASUS laptop running Ubuntu 26.04 LTS 24/7 for DNS filtering, internal HTTPS reverse proxy, private cloud, media streaming, NAS storage, observability, lightweight LLMs, and VPN routing.
2. **On-Demand GPU Worker (`workstation`):** A Windows 11 desktop with an **RTX 3080 (10 GB VRAM)** that stays asleep or powered off until I actually send a prompt to a larger LLM — waking up automatically via **Wake-on-LAN** and returning to **S3 Sleep** when idle.

---

## System Architecture

```mermaid
flowchart TB
    Remote["Remote Devices (Laptop / Phone / Tablet)<br/>5G or External Wi-Fi (PWAs & Native Apps)"]
    Router["Wi-Fi 7 Router (MLO)<br/>Zero Port Forwarding | Isolated Guest Subnet"]

    subgraph LAN["Private Home LAN (IPv4 + IPv6)"]
        subgraph Server["24/7 Server (Ubuntu 26.04 LTS — i7-8750H, 16 GB RAM)"]
            TS["Tailscale Subnet Router<br/>+ Split DNS"]
            AG["AdGuard Home<br/>Network-Wide DNS (DoH Quad9) & Rewrites"]
            CD["Caddy Reverse Proxy<br/>Wildcard Let's Encrypt HTTPS (DNS-01)"]
            OW["Open WebUI + Ollama (CPU)"]
            WOL["Custom Python WoL Proxy"]
            MON["Uptime Kuma v2 + Beszel<br/>Unix Socket Metrics & TLS/Backup Checks"]
            Core["Nextcloud + MariaDB | Jellyfin<br/>Minecraft (Nebula Mesh) | Bots | Portainer"]
            SMB["Samba NAS"]
            BK["Restic + Rclone<br/>Daily 03:00 Encrypted Backup"]
        end

        subgraph Desktop["On-Demand GPU Node (Ryzen 5600X + RTX 3080 10 GB)"]
            OLGPU["Ollama Boot Service (pre-login)<br/>7B/8B Models 100% VRAM"]
            SLEEP["Auto-Sleep Task (S3)<br/>Only when no user logged in & VRAM idle"]
        end
    end

    Cloud["Cloud Storage (5 TB)<br/>Client-Side AES-256 Encrypted Snapshots"]
    TG["Private Telegram Bot<br/>Downtime, Thermal, Disk & UPS Battery Alerts"]

    Remote -->|"WireGuard Tunnel"| TS
    Router --- LAN
    TS --> CD
    CD --> OW
    CD --> Core
    CD --> MON
    OW --> WOL
    WOL -->|"1. Magic Packet (if offline)<br/>2. Stream Inference"| OLGPU
    BK -->|"Encrypted Deduplicated Blocks"| Cloud
    BK -.->|"Success Push Heartbeat"| MON
    MON -->|"Real-Time Alerts"| TG
```

---

## Hardware & 24/7 Laptop Hygiene

| Node | Hardware | Role |
| :--- | :--- | :--- |
| **Server (24/7)** | Intel i7-8750H (6C/12T), 16 GB RAM, 256 GB SSD (OS) + 1 TB HDD (Data) | Core services, Docker host (13 containers), NAS, DNS, Reverse Proxy, VPN |
| **GPU Workstation** | AMD Ryzen 5 5600X, 32 GB RAM, NVIDIA RTX 3080 (10 GB VRAM) | Development workstation + on-demand LLM inference |
| **Mobile & Remote** | Ryzen 7 5800H Laptop, Flagship Phone (Wi-Fi 7 MLO), Tablet | Remote HTTPS PWAs & native apps via Tailscale Split DNS + SMB |

* **Battery Protection & Built-In UPS:** A custom `systemd` unit pins `/sys/class/power_supply/BAT0/charge_control_end_threshold` to **60%** on every boot (bypassing the battery in AC idle at ~58%). Combined with Beszel's `< 40%` battery alert, the laptop battery doubles as a free **power-outage UPS** with Telegram alerting.
* **Disk & Thermal Monitoring:** `smartmontools` (`smartd`) + Beszel (`hwmon`) track SMART health and temperatures continuously; CPU idles around **46 °C** with ~5 GB / 14 GB RAM used across 13 containers.

---

## Services Stack

| Category | Stack | Purpose |
| :--- | :--- | :--- |
| **Reverse Proxy & TLS** | Caddy (`caddy-dns/duckdns`) | Internal HTTP/2 & HTTP/3 wildcard HTTPS via Let's Encrypt DNS-01 (zero WAN ports) |
| **Observability & Alerts** | Uptime Kuma v2 + Beszel | Service/TLS monitoring, backup heartbeats, CPU/RAM/thermal/battery metrics & Telegram alerts |
| **Network & DNS** | AdGuard Home | Network-wide ad/tracker blocking (IPv4 + IPv6 Link-Local DNS, Quad9 DoH) & local DNS rewrites |
| **Remote Access** | Tailscale + Nebula | Private WireGuard Subnet Router + Split DNS (personal devices) & isolated Nebula mesh (Minecraft) |
| **Local AI** | Open WebUI + Ollama | Unified PWA chat UI backed by both 24/7 CPU models and on-demand RTX 3080 models |
| **Private Cloud & Media** | Nextcloud + MariaDB, Jellyfin | Self-hosted file sync and media server behind Caddy HTTPS |
| **Storage** | Samba (SMB) | Structured LAN/Tailscale NAS accessible natively on Windows & Android |
| **Management & Bots** | Portainer + Docker Compose | Stack orchestration plus 2 custom automation bots |

---

## Highlight 1: Hands-Free RTX 3080 Offload (WoL Proxy + Auto-Sleep)

1. **Zero-Dependency Python Streaming Proxy ([`scripts/ollama-wol-proxy.py`](scripts/ollama-wol-proxy.py)):**
   * Caches `/api/tags` and `/api/version` locally so GPU models remain visible in Open WebUI while the desktop is off — background polling never triggers accidental wakeups.
   * On inference requests (`/api/chat`, `/api/generate`, `/v1/*`), if the workstation is offline, it sends a **Wake-on-LAN Magic Packet**, waits until Ollama responds, and streams tokens back in real time.
2. **Pre-Login Windows Boot Service:**
   * A Windows Scheduled Task (`SYSTEM`) launches `ollama serve` at boot with `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KEEP_ALIVE=10m`, working even at the lock screen.
3. **Smart Auto-Sleep ([`scripts/check-idle-autosleep.ps1`](scripts/check-idle-autosleep.ps1)):**
   * Runs every 5 minutes and suspends to **S3 Sleep (~2–4 W, ~3 s next wake)** only when:
     1. No interactive user session (`explorer.exe` absent — never interrupts gaming/coding or `Win+L`);
     2. Zero models loaded in VRAM (`/api/ps` empty) and no active TCP connections on Ollama's port;
     3. Two consecutive idle checks (~10 min after VRAM unload).

---

## Highlight 2: Zero-Exposed-Port Internal HTTPS & Observability

* **Wildcard TLS Without Exposing WAN Ports ([`scripts/Caddyfile.example`](scripts/Caddyfile.example)):**
  * Built from the official `caddy:2-builder` with `github.com/caddy-dns/duckdns` using Let's Encrypt **DNS-01** validation.
  * Public DNS points strictly to `127.0.0.1` (never leaking home WAN or LAN IPs); **AdGuard Home DNS Rewrites** resolve `*.<domain>` inside the LAN, and **Tailscale Split DNS** routes the exact same hostnames over 5G/external Wi-Fi.
  * Enables clean PWAs (Open WebUI, Uptime Kuma, Beszel) and native Android apps (Jellyfin, Nextcloud) with valid trusted certificates everywhere.
* **Observability & Automated Alerting:**
  * **Beszel + Agent** communicate over a local **Unix socket** (zero extra TCP ports exposed), tracking CPU, RAM, `/`, `/data`, thermals, containers, and battery/UPS status.
  * **Uptime Kuma v2** (bound to `127.0.0.1`) monitors all HTTPS endpoints, TLS certificate expiry, and daily backup heartbeats — firing instant alerts to a private **Telegram** bot.

---

## Highlight 3: Automated Encrypted Offsite Backups

Implemented in [`scripts/homelab-backup.sh`](scripts/homelab-backup.sh) and triggered daily at `03:00` via `systemd` timer (`Nice=10`, `IOSchedulingClass=idle`):

1. Takes a consistent compressed SQL dump of MariaDB (`--single-transaction --quick`) before backing up.
2. Uses **Restic + Rclone** (dedicated OAuth Client ID, `--pack-size 64`, `--tpslimit 2`) to upload deduplicated, **client-side AES-256 encrypted** snapshots.
3. Covers application data, Docker named volumes, Samba shares, and critical `/etc` configs with automated retention (`14 daily / 4 weekly / 6 monthly`) and integrity checks (`restic check`).
4. Sends a **Push Heartbeat** to Uptime Kuma strictly on success (`set -euo pipefail`); any missed or failed night triggers an immediate Telegram alert.

---

## Security & Network Hardening

* **Zero Exposed WAN Ports:** No IPv4/IPv6 port forwarding, DMZ, UPnP, WPS, or WAN ICMP ping enabled on the router.
* **Network Segmentation:** Dedicated Wi-Fi 7 MLO SSID (WPA3), isolated Guest Wi-Fi subnet, and strict Nebula firewall rules allowing friends only TCP `25565` (Minecraft).
* **SSH, Proxy & Host Firewall:** OpenSSH hardened to **Ed25519 keys only** (`PasswordAuthentication no`, `PermitRootLogin no`). `ufw` restricts SSH and Portainer strictly to trusted static IPs and Tailscale CIDR, restricts Caddy (`80/443`) to LAN/Tailscale, and binds local AI proxy ports strictly to `docker0`. Portainer's HTTPS route enforces an additional `remote_ip` allowlist in Caddy.
* **Endpoint Security:** Workstation SMB shares enforce **SMB3 encryption** (`EncryptData = True`) on Private network profiles only with dedicated hidden local credentials.

---

## Disclaimer

All scripts and configurations in this repository are **sanitized templates** using placeholder domains, IPs, MAC addresses, and paths. No real credentials, tokens, certificates, or private network identifiers are stored here.