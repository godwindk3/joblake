# 🌊 JobLake Data Pipeline

> A lightweight, scalable data engineering project designed to scrape, standardize, and index job market data with high performance.

---

## 🏗️ System Architecture

The architecture follows the **Medallion Architecture** (Bronze, Silver, Gold), orchestrated by Apache Airflow.

```mermaid
graph TD
    %% Control Plane
    subgraph Control_Plane [Orchestration]
        A([⚙️ Apache Airflow])
    end

    %% Data Sources
    subgraph Data_Sources [External Data]
        S[🌐 Job Boards & Facebook]
    end

    %% Data Lake Layers
    subgraph Bronze [Bronze Layer - Raw Storage]
        M[(🪣 MinIO)]
    end

    subgraph Silver [Silver Layer - Processing]
        P[🐼 Python + Pandas]
    end

    subgraph Gold [Gold Layer - Serving]
        PG[(🐘 PostgreSQL)]
        ES[(🔍 Elasticsearch)]
    end

    subgraph Visualization [UI & Monitoring]
        K[📊 Kibana]
    end

    %% Data Flow (Solid Lines)
    S -- "Extract / Dump (JSON/HTML)" --> M
    M -- "Read / Cleanse / Deduplicate" --> P
    P -- "Load Relational Data" --> PG
    P -- "Index Full-Text Search" --> ES
    ES -- "Connect & Query" --> K

    %% Control Flow (Dotted Lines)
    A -. "Triggers Scraper Scripts" .-> S
    A -. "Triggers Pandas Pipeline" .-> P

    %% Styling
    classDef bronze fill:#cd7f32,stroke:#333,stroke-width:1px,color:#fff;
    classDef silver fill:#c0c0c0,stroke:#333,stroke-width:1px,color:#000;
    classDef gold fill:#ffd700,stroke:#333,stroke-width:1px,color:#000;
    
    class M bronze;
    class P silver;
    class PG,ES gold;