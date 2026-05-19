# SC Community SHOWER

SHOpfront · Workorder · Exchange Register

Community inventory management server for Star Citizen organizations. Integrates with Discord for authentication and PITS via JOCK Strap for real-time inventory sync.

## Features

- Discord OAuth login with guild verification
- Community inventory browsing with quality/quantity filters
- User inventory management (add/delete items)
- Order request system
- Notification delivery
- Admin panel with role/user management
- Dark/light theme toggle
- WebSocket server for real-time sync with PITS

## Quick Start

1. Clone the repo
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and configure Discord credentials
4. `python server.py`

### Discord Setup

1. Create an application at https://discord.com/developers/applications
2. Add OAuth2 redirect URI: `http://localhost:9200/auth/callback`
3. Enable the bot with "Send Messages" and "Read Messages" intents

## Deploy to Azure

See `.github/workflows/deploy.yml` for the CI/CD pipeline. Requires:
- Azure Container Registry
- Azure App Service (Linux, Docker)
- Service principal for deployment

## API

### WebSocket (`ws://host:9200`)

Supports JOCK Strap extension for bidirectional inventory sync.

## License

MIT
