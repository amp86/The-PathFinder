# The-PathFinder
The PathFinder scouts and summarizes the best flight and hotel combinations, providing the perfect groundwork for your booking.

This project demonstrates a robust, concurrent travel planning system built using the Google Agent Development Kit (ADK). It uses a specialized team of agents to efficiently handle complex, multi-part user queries (e.g., "Find me a flight and book a hotel for my trip next month").

Category 1: The Pitch (Problem, Solution, Value)
The Problem: The Cognitive Burden of Fragmented Planning
Travel planning is an inherently composite task. A user's natural query, such as "Find me a flight from Madrid to Barcelona for next month and book a hotel for the first week," demands specialized information gathering. Traditional single-agent models often fail here because they struggle to segment the distinct data (flight codes vs. hotel cities) and frequently get confused, leading to an inconsistent and frustrating user experience.

Our Solution: Agentic Division of Labor and Concurrency
Our solution is a Multi-Agent Travel Planner designed around the principle of Division of Labor and Parallel Execution. The system transforms a fragmented search into a single, cohesive conversational interaction:
    1. Decomposition: The query is broken into discrete, structured sub-tasks.
    2. Concurrency: A ParallelAgent simultaneously dispatches these sub-tasks to specialist agents (Flight and Hotel).
    3. Synthesis: A final AggregatorAgent combines all results (and any missing information requests) into one final response.
Core Concept & Value Proposition
    • Innovation: Parallel Efficiency: The use of the ParallelAgent for independent flight and hotel searches significantly reduces the total response time, mimicking how a human would open two browser tabs at once.
    • Value: We reduce the user's cognitive load by offering a single, powerful conversational interface, saving significant time.
    • Modularity: The architecture is easily extensible. Adding a new service (e.g., car rental) only requires creating a new specialist agent and integrating it into the existing parallel workflow.

Category 2: The Technical Journey & Architecture
High-Level Architecture
The application uses a strict, hierarchical ADK workflow to ensure reliability and performance. .
ADK Agent Type	Role in System	Key Function
SequentialAgent	Orchestrator (root_agent)	Defines the execution pipeline: Decompose -> Search -> Aggregate.

Agent description is in the below image:
![alt text](image-1.png)

Technical Challenges & Solutions
The development journey focused on solving the inherent complexity of concurrent execution and context management.
The Parallel Leakage Problem (State Management)
The most critical challenge was preventing the context of the original composite query from "leaking" into the specialist agents running in parallel.
    • Initial Issue: When the system passed the full conversation history to the ParallelAgent's sub-agents, the Flight Specialist would sometimes hallucinate about hotels, and the Hotel Specialist would be distracted by flight details, despite strict prompt instructions. The agents were seeing the entire unsegmented user input.
    • The Solution: Structured Input Enforcement: We enforced a pivotal design decision using Pydantic and strict input control.
        1. The query_decomposer_agent was forced to output a single, structured DecomposedJSON object.
        2. The input to the specialist agents was then explicitly restricted to only the specific field from that JSON, not the full context. For example, the Hotel Specialist's instruction is: **Your ONLY input is the pre-formatted hotel query: {raw_decomposed_json.hotel_query}. Ignore any mentions of flights in the input**.
This rigorous input constraint forced the agents to discard the original, ambiguous query and focus solely on the clean, segmented data, resolving the context leakage issue and making the parallel execution reliable.

Setup and Installation
1. Project Structure
Your repository should have the following file structure:
travel-planner-adk/
├── README.md                 <-- This file
├── .env                      <-- API Keys (DO NOT commit this file!)
├── agent.py                  <-- The ADK Multi-Agent Orchestration Logic
├── amadeus_tool.py           <-- The Custom Tool Logic (Amadeus API calls)
└── requirements.txt          <-- Dependencies (google-adk, requests, python-dotenv)

2. Prerequisites
    • Python 3.10+
    • A Google Gemini API Key.
    • An Amadeus for Developers API Key and Secret.
3. Installation
    1. Clone the repository:
Bash

git clone [YOUR_REPO_URL]
cd travel-planner-adk
    2. Create and activate a virtual environment:
Bash

python -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# .venv\Scripts\activate.bat # On Windows CMD
    3. Install dependencies:
Bash

pip install -r requirements.txt
# Note: You need `google-adk`, `requests`, and `python-dotenv`.
    4. Configure API Keys:
Create a file named .env in the root directory and add your credentials. Ensure .env is listed in your .gitignore file.
Ini, TOML

# .env
GOOGLE_API_KEY="YOUR_GEMINI_API_KEY_HERE"
AMADEUS_API_KEY="YOUR_AMADEUS_CLIENT_ID"
AMADEUS_API_SECRET="YOUR_AMADEUS_CLIENT_SECRET"
4. Running the Agent
The agent.py file is configured to be run using the ADK's API server and developer UI for easy debugging.
    1. Run the ADK Web Server:
Bash

adk web agent.py
    2. Access the UI:
Open your browser to the URL displayed (usually http://localhost:8000).
    3. Test Query:
Test the concurrent execution with a composite query:
"Find me a flight from New York (JFK) to London (LHR) on 2026-02-15 with return on 2026-02-18 for 1 adult, and also find hotels in London (LON) between the same dates for 1 adult."

Here is the architectural diagram of my solution:
![alt text](image-2.png)

