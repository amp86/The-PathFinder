from dotenv import load_dotenv

load_dotenv()

import asyncio
from typing import Any, Dict

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.models.google_llm import Gemini
from google.adk.sessions import DatabaseSessionService
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.adk.tools import google_search
from .amadeus_tool import search_amadeus_flights, search_amadeus_hotels
from google.genai import types
import os
from pydantic import BaseModel
from google.adk.tools import google_maps_grounding
#from google.adk.tools import ToolContext
import logging
logging.basicConfig(level=logging.DEBUG)

APP_NAME = "agents"  # Application
USER_ID = "default"  # User
SESSION = "default"  # Session

MODEL_NAME = "gemini-2.5-flash-lite"
try: 
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
except Exception as e:
    print("Please set your GOOGLE_API_KEY environment variable.")
    raise e

print(f"API Key Status: {'Loaded' if GOOGLE_API_KEY else 'MISSING'}")

# Configure retry options for handling transient errors
retry_config = types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504],  # Retry on these HTTP errors
)

# Define helper functions that will be reused throughout the notebook
async def run_session(
    runner_instance: Runner,
    user_queries: list[str] | str = None,
    session_service: InMemorySessionService = None,
    session_name: str = "default",
):
    print(f"\n ### Session: {session_name}")

    # Get app name from the Runner
    #app_name = runner_instance.app_name

    # Attempt to create a new session or retrieve an existing one
    try:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_name
        )
    except:
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_name
        )

    # Process queries if provided
    if user_queries:
        # Convert single query to list for uniform processing
        if type(user_queries) == str:
            user_queries = [user_queries]

        # Process each query in the list sequentially
        for query in user_queries:
            print(f"\nUser > {query}")

            # Convert the query string to the ADK Content format
            query = types.Content(role="user", parts=[types.Part(text=query)])

            # Stream the agent's response asynchronously
            async for event in runner_instance.run_async(
                user_id=USER_ID, session_id=session.id, new_message=query
            ):
                # Check if the event contains valid content
                if event.content and event.content.parts:
                    # Filter out empty or "None" responses before printing
                    if (
                        event.content.parts[0].text != "None"
                        and event.content.parts[0].text
                    ):
                        print(f"{event.author} > ", event.content.parts[0].text)
    else:
        print("No queries!")

# Define our output schema using a Pydantic model
class DecomposedJSON(BaseModel):
    flight_query: str
    hotel_query: str

# Step 1: Define the Agents
query_decomposer_agent = LlmAgent(
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    name="query_decomposer_agent",
    instruction="""Analyze the user's request:  
    Your ONLY output must be a valid JSON object with two keys: 'flight_query' and 'hotel_query'.
    For each key, extract the relevant parameters (dates, cities, people) from the user's request.
    **Crucially, you MUST convert all dates into the absolute YYYY-MM-DD format.** For example, if the user says "next month" and the current date is 2025-10-28, you must resolve this to the correct date in the following month.
    Example Format: 
    {
      "flight_query": "Find flight from MAD to BCN on 2025-12-01 for 1 adult.",
      "hotel_query": "Find hotels in Barcelona from 2025-12-01 to 2025-12-10 for 1 adult."
    }
    """,
    # This key saves the entire raw JSON string output for the next agent to read
    output_schema=DecomposedJSON,
    output_key="raw_decomposed_json", 
)

# Step 1: Create the LLM Agent
# This new agent is specialized for finding flights using the Amadeus API.
amadeus_flight_agent = LlmAgent(
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    name="amadeus_flight_agent",
    instruction="""**Your ONLY input is the pre-formatted flight query: {raw_decomposed_json.flight_query}. Ignore any mentions of hotels in the input**
    You are a flight booking assistant. Your only goal is to find flight options using the 'search_amadeus_flights' tool.
    From this input, extract the required parameters: 'origin_location_code', 'destination_location_code', 'departure_date', and 'adults'. The dates will already be in YYYY-MM-DD format.
    Do not attempt to calculate or convert dates.
    If any parameters are missing from this specific input, ask the user for the missing information.
    Once you have all parameters, call the 'search_amadeus_flights' tool.""",
    description="An agent that uses the Amadeus API to find flights.",
    tools=[search_amadeus_flights],
    output_key="flights_agent_output",
)
# This is the new, separate agent specifically for Amadeus hotel searches.
amadeus_hotel_agent = LlmAgent(
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    name="amadeus_hotel_agent",
    instruction="""**Your ONLY input is the pre-formatted hotel query: {raw_decomposed_json.hotel_query}. Ignore any mentions of flights in the input**
    You are a hotel booking assistant. Your primary goal is to find hotel options using the 'search_amadeus_hotels' tool.
    From this input, extract the required parameters: 'city_code', 'check_in_date', 'check_out_date', and 'adults'. The dates will already be in YYYY-MM-DD format.
    Do not attempt to calculate or convert dates.
    If the user provides a specific hotel name or ID instead of a city, you MUST inform them that you can only search by city and ask for a city name.
    If any parameters are missing from this specific input, ask the user for the missing information.
    Once you have all required parameters, call the 'search_amadeus_hotels' tool.""",
    description="An agent that uses the Amadeus API to find hotels.",
    tools=[search_amadeus_hotels],
    output_key="hotel_agent_output",
)

# The root agent now orchestrates the parallel search and synthesizes the results.
aggregator_agent = LlmAgent(
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    name="travel_planner_agregator_agent",
    instruction="""
    You are the final, master travel planner. Your task is to synthesize the search results from the flight and hotel specialists.

    1. **Flight Summary:** Review the content of the {flights_agent_output} and summarize the best flight options found, including dates, origin, destination, and key price points.
    2. **Hotel Summary:** Review the content of the {hotel_agent_output} and summarize the best hotel options found, including the city, dates, and accommodation details.
    3. **Action Required:** If *either* specialist agent reported that information was missing (e.g., asked for a missing date or city), clearly communicate to the user which information is still needed to complete that part of the plan.
    4. **Use the google_maps_grounding tool to estimate the best route and travel times from the airport locations to the hotel locations. You can use the tool: google_maps_grounding.
    5. **Final Presentation:** Combine both summaries into a single, cohesive, and easy-to-read travel plan for the user. Use clear headings and bullet points for the final response.
    """,
    description="A travel planner that orchestrates flight and hotel searches in parallel",
    tools=[google_maps_grounding],
)

# This ParallelAgent will run the flight and hotel searches concurrently.
search_specialists = ParallelAgent(
    name="search_specialists",
    sub_agents=[amadeus_flight_agent, amadeus_hotel_agent],
)

root_agent = SequentialAgent(
    name="travel_planner_root_agent",
    sub_agents=[query_decomposer_agent,search_specialists,aggregator_agent],
)

# Step 2: Set up Session Managementations in RAM (temporary)
session_service = InMemorySessionService()

# Step 3: Create the Runner
#runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)

# The 'app' object is what the 'adk web' command looks for.
root_agent_app = App(
    name=APP_NAME,                   # Use 'name' instead of 'app_name'
    #runner=runner           # Pass your SequentialAgent instance here
    root_agent=root_agent,
)

"""
async def main():
    "The main asynchronous entry point for the script."
    # Changed the input to a single query suitable for the travel planner.
    # This query will trigger the root agent to delegate to the amadeus_flight_agent.
    await run_session(
        runner,
        "Find me a flight from New York (JFK) to London (LHR) on 2026-02-15 with return on 2026-02-18 for 1 adult, 
        and also find hotels in London (LON) between the same dates for 1 adult.",
        session_service=session_service,
        session_name="amadeus-flight-and-hotel-session-1",
    )
if __name__ == "__main__":
    # Code here only runs when the script is executed directly
    asyncio.run(main())
"""