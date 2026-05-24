import asyncio
import os
import json
import logging
from agent import GmailInvoiceAgent, CACHE_FILE

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

async def verify_agent():
    logging.info("Starting verification of Gmail Invoice Agent in simulation mode...")
    
    # Initialize the agent in simulation mode
    agent = GmailInvoiceAgent(use_mock=True, sheet_id=None)
    
    # Trigger processing
    result = await agent.scan_and_process()
    
    logging.info(f"Agent finished processing. Status: {result.get('status')}")
    logging.info(f"Invoices generated: {result.get('invoices_found')}")
    
    # Assertions for sanity checking
    assert result["status"] == "success", "Agent did not finish successfully"
    assert result["invoices_found"] > 0, "No mock invoices were generated"
    assert os.path.exists(CACHE_FILE), "Cache file was not created by the agent"
    
    # Read the cache file to confirm structure is correct
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
        
    logging.info(f"Cache verified. Total cached rows: {len(cache_data)}")
    assert len(cache_data) == result["invoices_found"], "Cache size does not match generated size"
    
    # Check structure of first item
    first_item = cache_data[0]
    required_fields = ["service_name", "date", "amount", "currency", "category"]
    for field in required_fields:
        assert field in first_item, f"Required field '{field}' missing from cached invoice"
        
    logging.info("✅ All agent verification checks passed successfully!")
    print("\nAGENT VERIFICATION PASSED SUCCESSFULLY!\n")

if __name__ == "__main__":
    asyncio.run(verify_agent())
