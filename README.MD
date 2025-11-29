# Flask Image Generation Web App

A Flask-based web application for generating and managing images, integrating with **n8n**, **Runway**, and **Google Cloud Storage**. This app provides user authentication, a dashboard, admin controls, and seamless image upload and storage capabilities.

Website is available at: https://lora-gen-vercel.vercel.app/

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)

---

## Features

- User authentication and session management
- Admin panel with user and content controls
- Dashboard for managing generated images
- Image generation integration with **Runway** and models like **Nano Banana** and **Seedance**
- Image storage in **Google Cloud Storage**
- Maintenance mode with access restrictions
- Health check endpoint
- Pricing and FAQ pages

---

## Tech Stack

- **Backend:** Flask, Python  
- **Authentication & Routing:** Flask Blueprints  
- **Storage:** Google Cloud Storage  
- **Integrations:** n8n workflows, RunwayML models (Nano Banana, Seedance)  
- **Frontend:** HTML templates with Jinja2  
- **Hosting:** Render 