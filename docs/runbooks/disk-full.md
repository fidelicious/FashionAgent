# Disk full

## Symptom

- Hourly `disk_check` job posts a warning to your operator channel.
- `OSError: [Errno 28] No space left on device` in `docker compose logs`.
- New uploads via `/add_item` fail silently or with a vague error.

## Diagnose

```bash
# What's actually full?
df -h ~ /

# What's eating space inside ~/FashionAgent?
du -sh ~/FashionAgent/* | sort -h
du -sh ~/FashionAgent/images/* | sort -h
du -sh ~/FashionAgent/backups/

# Old Docker layers can also dominate:
docker system df
```

## Fix

In rough order of pain:

```bash
# 1. Prune Docker (safe — only touches unused images/containers/build cache):
docker system prune -a

# 2. Drop ancient backups that survived the retention window for some
#    reason (the nightly job should handle this; manual cleanup is a
#    backstop):
find ~/FashionAgent/backups -name 'clawbot-*.tar.gz' -mtime +30 -delete

# 3. images/raw/ holds the originals. Once a cutout exists in
#    images/cutouts/<same-uuid>.png, the raw file is *technically*
#    redundant. Confirm before deleting:
ls ~/FashionAgent/images/raw/ | head -5
ls ~/FashionAgent/images/cutouts/ | head -5
# If every raw has a matching cutout, archiving raw/ off-host is safe:
tar -czf /external-drive/fashionagent-raw-$(date +%F).tar.gz \
  -C ~/FashionAgent/images raw
rm -rf ~/FashionAgent/images/raw/*

# 4. logs/ accumulates if rotation isn't working:
ls -lht ~/FashionAgent/logs/ | head -10
# Drop logs older than 30 days:
find ~/FashionAgent/logs -type f -mtime +30 -delete
```

## Prevent

- Lower `backup.retain_days` in `config/clawbot.yaml` if backups are the dominant consumer.
- Add `"**/raw/**"` to `backup.exclude_globs` so the nightly tarball doesn't double-store originals.
- Tune `health.disk_warn_pct` (default 85%) lower if you want earlier warnings.
- `du -sh ~/FashionAgent/*` once a month so disk creep doesn't surprise you.
