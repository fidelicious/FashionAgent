# Discord token expired (or leaked)

## Symptom

- Bot shows offline (grey dot) in your Discord member list.
- `docker compose logs -f clawbot` shows `LoginFailure: Improper token has been passed.`
- Slash commands don't autocomplete in Discord.

## Diagnose

```bash
# 1. Is the container running but failing the login?
docker compose -f ~/FashionAgent/docker/docker-compose.yml ps
docker compose -f ~/FashionAgent/docker/docker-compose.yml logs clawbot --tail 50

# 2. Is DISCORD_TOKEN actually present and readable?
docker exec clawbot printenv | grep DISCORD
# (Should print DISCORD_TOKEN=… and DISCORD_USER_ID=…)
```

## Fix

1. Open https://discord.com/developers/applications, pick your bot, **Bot** tab.
2. Click **Reset Token**. Copy the new value immediately — Discord shows it once.
3. Update the secrets file on the NUC:
   ```bash
   $EDITOR ~/FashionAgent/secrets/.env
   # DISCORD_TOKEN=<new value>
   chmod 600 ~/FashionAgent/secrets/.env
   ```
4. Restart the container:
   ```bash
   docker compose -f ~/FashionAgent/docker/docker-compose.yml restart clawbot
   ```
5. Verify in Discord — the bot's status dot should turn green within a few seconds.

## Prevent

- `secrets/.env` is gitignored. Don't commit it. Don't paste it into chat or screenshots.
- Rotate the token if you ever share your screen showing it, or if a collaborator leaves.
- The Discord Developer Portal will email you about leaked tokens it detects (e.g. on GitHub) and auto-rotate; don't ignore those emails.
