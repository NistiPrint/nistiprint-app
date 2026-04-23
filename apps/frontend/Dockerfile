# nistiprint-frontend/Dockerfile
# Stage de build
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

# Define ARGs para receber as variáveis de ambiente do Vite no build
ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY

# Assegura que as variáveis sejam reconhecidas pelo build do Vite
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

RUN npm run build

# Stage de produção
FROM nginx:stable-alpine
ENV TZ=America/Sao_Paulo
RUN apk add --no-cache tzdata
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
