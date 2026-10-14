"""Server entry point.

Run on the shop PC (see README for HTTPS):
    uvicorn server.main:app --host 0.0.0.0 --port 8443 \
        --ssl-certfile data/certs/server.pem --ssl-keyfile data/certs/server.key
"""

from server.api.app import create_app

app = create_app()
