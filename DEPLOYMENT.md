# StreamStack Deployment Guide

This guide covers deploying StreamStack in various environments from development to production.

## Quick Start

### Development Setup

1. **Clone and Install**
   ```bash
   git clone https://github.com/alexyujiuqiao/streamstack.git
   cd streamstack
   pip install -e ".[dev]"
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **Start Development Server**
   ```bash
   # Option 1: Direct Python
   python -m streamstack.main
   
   # Option 2: Uvicorn with reload
   uvicorn streamstack.main:app --reload --host 0.0.0.0 --port 8000
   ```

### Docker Compose (Recommended)

1. **Start All Services**
   ```bash
   docker-compose up -d
   ```

2. **View Logs**
   ```bash
   docker-compose logs -f api
   ```

3. **Access Services**
   - API: http://localhost:8000
   - Grafana: http://localhost:3000 (admin/admin)
   - Prometheus: http://localhost:9090
   - Jaeger: http://localhost:16686

## Production Deployment

### Prerequisites

- Docker and Docker Compose
- Redis instance
- (Optional) GPU for vLLM
- Load balancer (nginx, traefik, etc.)

### Environment Configuration

1. **Create Production Environment File**
   ```bash
   cp .env.example .env.prod
   ```

2. **Configure Production Settings**
   ```env
   # .env.prod
   STREAMSTACK_DEBUG=false
   STREAMSTACK_LOG_LEVEL=INFO
   STREAMSTACK_WORKERS=4
   
   # Use production OpenAI key
   OPENAI_API_KEY=sk-prod-key-here
   
   # Production Redis
   STREAMSTACK_REDIS_URL=redis://prod-redis:6379/0
   
   # Restrictive CORS
   STREAMSTACK_CORS_ORIGINS=["https://yourdomain.com"]
   
   # Higher rate limits for production
   STREAMSTACK_RATE_LIMIT_REQUESTS_PER_MINUTE=1000
   STREAMSTACK_RATE_LIMIT_TOKENS_PER_MINUTE=50000
   ```

### Docker Compose Production

1. **Create Production Compose File**
   ```yaml
   # docker-compose.prod.yml
   version: '3.8'
   
   services:
     api:
       build: .
       env_file: .env.prod
       deploy:
         replicas: 3
         resources:
           limits:
             memory: 1GB
           reservations:
             memory: 512MB
       restart: unless-stopped
       
     redis:
       image: redis:7-alpine
       command: redis-server --appendonly yes --maxmemory 1gb
       volumes:
         - redis_data:/data
       restart: unless-stopped
       
     nginx:
       image: nginx:alpine
       ports:
         - "80:80"
         - "443:443"
       volumes:
         - ./nginx.conf:/etc/nginx/nginx.conf
         - ./ssl:/etc/ssl/certs
       depends_on:
         - api
       restart: unless-stopped
   ```

2. **Deploy**
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

### Kubernetes Deployment

1. **Create Namespace**
   ```yaml
   # namespace.yaml
   apiVersion: v1
   kind: Namespace
   metadata:
     name: streamstack
   ```

2. **ConfigMap**
   ```yaml
   # configmap.yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: streamstack-config
     namespace: streamstack
   data:
     STREAMSTACK_REDIS_URL: "redis://redis:6379/0"
     STREAMSTACK_ENABLE_METRICS: "true"
     STREAMSTACK_ENABLE_TRACING: "true"
   ```

3. **Deployment**
   ```yaml
   # deployment.yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: streamstack-api
     namespace: streamstack
   spec:
     replicas: 3
     selector:
       matchLabels:
         app: streamstack-api
     template:
       metadata:
         labels:
           app: streamstack-api
       spec:
         containers:
         - name: api
           image: streamstack:latest
           ports:
           - containerPort: 8000
           envFrom:
           - configMapRef:
               name: streamstack-config
           - secretRef:
               name: streamstack-secrets
           resources:
             requests:
               memory: "512Mi"
               cpu: "250m"
             limits:
               memory: "1Gi"
               cpu: "500m"
           livenessProbe:
             httpGet:
               path: /health/live
               port: 8000
             initialDelaySeconds: 30
             periodSeconds: 10
           readinessProbe:
             httpGet:
               path: /health/ready
               port: 8000
             initialDelaySeconds: 5
             periodSeconds: 5
   ```

4. **Service**
   ```yaml
   # service.yaml
   apiVersion: v1
   kind: Service
   metadata:
     name: streamstack-api
     namespace: streamstack
   spec:
     selector:
       app: streamstack-api
     ports:
     - port: 8000
       targetPort: 8000
     type: ClusterIP
   ```

### Load Balancer Configuration

#### Nginx Configuration

```nginx
# nginx.conf
upstream streamstack_backend {
    least_conn;
    server api1:8000;
    server api2:8000;
    server api3:8000;
}

server {
    listen 80;
    server_name your-domain.com;
    
    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    ssl_certificate /etc/ssl/certs/cert.pem;
    ssl_certificate_key /etc/ssl/private/key.pem;
    
    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    
    location / {
        limit_req zone=api burst=20 nodelay;
        
        proxy_pass http://streamstack_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Streaming support
        proxy_buffering off;
        proxy_cache off;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 300s;
    }
    
    # Health check endpoint
    location /health {
        access_log off;
        proxy_pass http://streamstack_backend;
    }
    
    # Metrics endpoint (restrict access)
    location /metrics {
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://streamstack_backend;
    }
}
```

## Monitoring and Alerting

### Prometheus Alerts

```yaml
# alerts.yml
groups:
- name: streamstack
  rules:
  - alert: StreamStackDown
    expr: up{job="streamstack-api"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "StreamStack API is down"
      
  - alert: HighLatency
    expr: histogram_quantile(0.95, rate(streamstack_http_request_duration_seconds_bucket[5m])) > 2
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High API latency"
      
  - alert: HighErrorRate
    expr: rate(streamstack_http_requests_total{status_code=~"5.."}[5m]) > 0.1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High error rate"
      
  - alert: QueueBacklog
    expr: streamstack_queue_depth > 100
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Request queue backlog"
```

### Grafana Dashboards

Import the provided dashboard JSON from `grafana/dashboards/streamstack-dashboard.json`.

## Scaling Considerations

### Horizontal Scaling

1. **API Instances**: Run multiple API instances behind a load balancer
2. **Redis Clustering**: Use Redis Cluster for high availability
3. **vLLM Scaling**: Deploy multiple vLLM instances with different models

### Vertical Scaling

1. **Memory**: Increase memory for higher concurrency
2. **CPU**: More CPU cores for better performance
3. **GPU**: Add GPUs for vLLM inference

### Performance Tuning

1. **Worker Processes**: Set `STREAMSTACK_WORKERS` based on CPU cores
2. **Redis Connections**: Tune `STREAMSTACK_REDIS_MAX_CONNECTIONS`
3. **Rate Limits**: Adjust based on capacity
4. **Queue Size**: Set `STREAMSTACK_MAX_QUEUE_SIZE` appropriately

## Security Best Practices

1. **API Keys**: Use strong, rotated API keys
2. **CORS**: Restrict to specific domains
3. **Rate Limiting**: Implement appropriate limits
4. **TLS**: Use HTTPS in production
5. **Network Security**: Use VPCs and security groups
6. **Secrets Management**: Use proper secret management systems

## Backup and Recovery

1. **Redis Data**: Regular Redis backups
2. **Configuration**: Version control all configs
3. **Logs**: Centralized log aggregation
4. **Metrics**: Long-term metrics storage

## Troubleshooting

### Common Issues

1. **API Not Starting**
   - Check environment variables
   - Verify Redis connectivity
   - Check OpenAI API key

2. **High Latency**
   - Monitor provider response times
   - Check queue depth
   - Scale instances

3. **Rate Limit Errors**
   - Increase rate limits
   - Check Redis performance
   - Monitor traffic patterns

### Debugging Commands

```bash
# Check API health
curl http://localhost:8000/health

# View metrics
curl http://localhost:8000/metrics

# Check logs
docker-compose logs -f api

# Test chat completion
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-3.5-turbo","messages":[{"role":"user","content":"Hello"}]}'
```

## Support

For issues and questions:
1. Check the GitHub issues
2. Review logs and metrics
3. Consult the API documentation at `/docs`