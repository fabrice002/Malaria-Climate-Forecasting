# Dashboard image — static files served by nginx.
#
# There is no build stage: the app ships as native ES modules, so what you edit
# is what runs. That keeps the image tiny and removes the Node toolchain from
# the deployment path entirely.

FROM nginx:1.27-alpine

# Serve config (static files + /api proxy to the backend).
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Application. Ordered so the rarely-changing layers cache first.
# vendor/ holds Leaflet: it is not a CDN reference, so omitting it leaves the
# image with no mapping library at all.
COPY vendor/    /usr/share/nginx/html/vendor/
COPY index.html /usr/share/nginx/html/
COPY styles/    /usr/share/nginx/html/styles/
COPY src/       /usr/share/nginx/html/src/

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1
