# Placeholder until the customer UI from iambpg/insightengine_9515 is imported.
# nginxinc/nginx-unprivileged listens on 8080. Do not mount a volume over /usr/share/nginx/html
# or a later real image would be hidden.
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY placeholder/index.html /usr/share/nginx/html/index.html
COPY placeholder/healthz /usr/share/nginx/html/healthz
EXPOSE 8080
