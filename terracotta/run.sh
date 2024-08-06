#!/bin/sh

# Run terracotta server
gunicorn -w 3 -b 0.0.0.0:${TC_PORT} terracotta.server.app:app
