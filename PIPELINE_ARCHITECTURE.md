# ArchAI - Architectural Summary Pipeline Deep Dive

This document provides a detailed explanation of the asynchronous task processing pipeline used in this project. The architecture is designed to handle potentially long-running tasks, such as generating code summaries with Large Language Models (LLMs), without blocking the main application. It's built on a robust, scalable foundation using Celery, RabbitMQ, and Docker Compose.

## 1. High-Level Overview: The Restaurant Kitchen Analogy

The easiest way to understand this system is to think of a busy restaurant kitchen.

-   **The Goal**: To process customer orders (requests to summarize code) efficiently without making the customer wait at the counter.
-   **The Problem**: Cooking a complex dish (calling an LLM) takes time. If the front-desk manager tried to cook every dish themselves, the customer queue would quickly become unmanageable.
-   **The Solution**: A decoupled system.
    -   A **Manager** (`Dispatcher`) takes orders and places them on an **Order Rail**.
    -   An army of **Chefs** (`Workers`) watch the rail, pick up orders, and cook them.
    -   The **Order Rail** (`RabbitMQ`) is the message board that separates the manager from the chefs.
    -   A set of **Kitchen Rules** (`Celery`) dictates how orders are written, where the rail is, and what dishes the chefs know how to cook.

This architecture ensures that the system is scalable (just hire more chefs if orders pile up), reliable (if a chef drops a dish, another can pick it up), and efficient.

---

## 2. The Core Components & Their Implementation

Let's map the analogy to the actual components in our codebase.

### a. The Dispatcher (The Manager)

-   **Role**: To find profiles in the database that need an L1 summary and create a task for each one. It *produces* tasks but does not execute them.
-   **Implementation Detail**:
    -   **File**: `structural_scaffolding/pipeline/dispatcher.py`
    -   **Logic**: The `dispatch_l1_summary_tasks` function periodically queries the database for profiles with `summary_level = NONE`.
    -   **The "Aha!" Moment**: It calls `generate_l1_summary.apply_async(...)`. This function **does not run the summary generation code**. Instead, it serializes the task name and its arguments into a message and sends it to the message broker (RabbitMQ).

### b. RabbitMQ (The Message Broker / The Order Rail)

-   **Role**: A message broker that acts as the central "task mailbox". It receives task messages from the Dispatcher and holds them in a queue until a Worker is ready to process them.
-   **Implementation Detail**:
    -   **File**: `docker-compose.yml`
    -   **Logic**: A standard `rabbitmq:3.12-management` image is defined as a service. It requires no custom code.
    -   **The "Aha!" Moment**: RabbitMQ is the crucial middleman. It completely decouples the Dispatcher from the Worker. They don't know or care about each other's existence; they only care about the RabbitMQ address.

### c. The Worker (The Chef)

-   **Role**: To connect to RabbitMQ, wait for new task messages, and execute the code associated with those tasks. It *consumes* and executes tasks.
-   **Implementation Detail**:
    -   **File**: The tasks themselves are in `structural_scaffolding/pipeline/tasks.py`. The Worker is not a single file but a **process** you launch.
    -   **Logic**: A function like `generate_l1_summary` is decorated with `@celery_app.task`. This decorator registers the function with Celery's task registry, making it a "known recipe".
    -   **The "Aha!" Moment**: A Worker process is a long-running program that does one thing: it listens to a specific queue in RabbitMQ. When a message appears, it pulls it, reads the task name, finds the corresponding function in its registry, and executes it.

### d. Celery (The System / The Kitchen Rules)

-   **Role**: The framework that wires everything together. It provides the decorator to define tasks (`@task`) and the API to call them (`.apply_async`). It defines the structure and rules of engagement.
-   **Implementation Detail**:
    -   **File**: `structural_scaffolding/pipeline/celery_app.py`
    -   **Logic**: This file creates a `Celery` application instance. This is the central configuration point.
    -   **The "Aha!" Moment**: This file contains two critical pieces of configuration:
        1.  `broker=...`: This tells both the Dispatcher (when sending) and the Worker (when receiving) the address of the RabbitMQ server.
        2.  `include=[...]`: This tells the Worker process which modules to import at startup to find all the registered tasks (the `@celery_app.task` functions).

---

## 3. The End-to-End Workflow in Detail

Let's trace a single profile from pending to completed.

1.  **Startup**: You run `docker compose up`. This starts all services defined in `docker-compose.yml`, including `postgres`, `rabbitmq`, `dispatcher`, and one or more `worker`s.

2.  **Dispatching**:
    -   The `dispatcher` container runs its command: `python -m structural_scaffolding.pipeline.dispatcher --watch`.
    -   Inside its `while True` loop, `dispatch_l1_summary_tasks` in `dispatcher.py` queries the `postgres` database and finds a profile needing a summary.
    -   It calls `generate_l1_summary.apply_async(args=(profile_id,))`.
    -   Celery looks at the configuration in `celery_app.py`, finds the `broker` URL (`amqp://guest:guest@rabbitmq:5672//`), and sends a message to the `rabbitmq` container.

3.  **Queueing**:
    -   The message, containing `{"task": "structural_scaffolding.tasks.generate_l1_summary", "args": ["..."]}`, now sits inside a queue (e.g., `l1_summary_queue`) within the RabbitMQ server.

4.  **Execution**:
    -   A `worker` container is running a command like `celery -A structural_scaffolding.pipeline.celery_app worker`.
    -   At startup, this worker process read `celery_app.py` and, due to the `include` statement, it imported `tasks.py` and knows about the `generate_l1_summary` task.
    -   The worker is actively listening to the `l1_summary_queue` on `rabbitmq`. It sees the new message and pulls it.
    -   It reads the task name, looks it up in its internal registry, and finds the `generate_l1_summary` function in `tasks.py`.
    -   It executes the function, passing the `profile_id` as an argument. The task code runs, builds the LLM context, gets the summary, and finally persists the result back to the `postgres` database.

---

## 4. The Role of Docker Compose: The Conductor

`docker-compose.yml` is the orchestra conductor that brings all the individual players together and makes them work in harmony.

-   **Service Definition**: It defines the four services (`postgres`, `rabbitmq`, `dispatcher`, `worker`) as isolated containers.

-   **Networking**: Docker Compose creates a virtual network. This is how the `dispatcher` can connect to the database at the address `postgres:5432` and the broker at `rabbitmq:5672`. The service names (`postgres`, `rabbitmq`) automatically become resolvable hostnames within this private network.

-   **Configuration via Environment**: The link between the code and the infrastructure is made via environment variables.
    -   Look at the `dispatcher` service definition in `docker-compose.yml`:
    ```yaml
    environment:
      CELERY_BROKER_URL: amqp://guest:guest@rabbitmq:5672//
      STRUCTURAL_SCAFFOLD_DB_URL: postgresql+psycopg://archai:archai@postgres:5432/structural_scaffolding
    ```
    -   When the `dispatcher` container starts, these environment variables are set inside it.
    -   The Python code in `celery_app.py` and `database.py` reads these variables using `os.getenv()`. This is how the code knows the correct addresses for the other containers, without hardcoding them.

-   **Process Management**: It defines what command each container runs on startup, turning the code into a running, interconnected system.
    -   `dispatcher`: `command: python -m ... --watch` makes it a long-running poller.
    -   `worker`: Uses the default command from its `Dockerfile`, which is typically `celery ... worker`, making it a long-running task consumer.

By orchestrating these components, Docker Compose provides a single command (`docker compose up`) to launch the entire, complex distributed system for development and testing.
