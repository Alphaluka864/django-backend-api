# Django Shop Backend API

A RESTful shop backend built with Django REST Framework, PostgreSQL, and Redis. The project includes product and category management, inventory tracking, supplier and purchase-order workflows, seller management, customer orders, JWT authentication, and automated tests.

## Technology Stack

- Python
- Django
- Django REST Framework
- PostgreSQL
- Redis
- Simple JWT
- Gunicorn
- Docker Compose

## Features

- Product and category APIs
- Inventory movements and stock monitoring
- Supplier and purchase-order management
- Product review and approval workflows
- Seller applications and seller dashboards
- Customer checkout and order management
- Seller order fulfillment and status management
- JWT authentication and token refresh
- Request throttling and caching
- Automated tests

## Architecture

Docker Compose runs three services:

- `web`: Django application served by Gunicorn
- `db`: PostgreSQL database
- `redis`: Redis cache

The Dockerized API is exposed on `127.0.0.1:8001` by default. The PostgreSQL and Redis containers are accessible to the application through the internal Compose network.

## Prerequisites

- Docker Engine or Docker Desktop
- Docker Compose
- Git

## Configuration

Create your local environment file:

```bash
cp .env.example .env
