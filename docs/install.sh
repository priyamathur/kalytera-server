#!/bin/sh
set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo ""
echo "${CYAN}Kalytera — LLM evaluation for production agents${RESET}"
echo "─────────────────────────────────────────────────"
echo ""

# Install SDK
echo "Installing kalytera SDK..."
pip install kalytera --quiet
echo "${GREEN}✓ kalytera installed${RESET}"
echo ""

# Check for API key
if [ -z "$KALYTERA_API_KEY" ]; then
  echo "${YELLOW}Next: get your free API key${RESET}"
  echo ""
  echo "  1. Open https://kalytera.dev and click 'Get started free'"
  echo "  2. Copy your key (starts with kly_live_...)"
  echo "  3. Add it to your shell:"
  echo "     export KALYTERA_API_KEY=\"kly_live_...\""
  echo ""
else
  echo "${GREEN}✓ KALYTERA_API_KEY detected${RESET}"
  echo ""
fi

echo "Add to your agent:"
echo ""
echo "  import kalytera, os"
echo "  kalytera.configure(api_key=os.environ['KALYTERA_API_KEY'])"
echo ""
echo "  kalytera.trace("
echo "    session_id=session_id,"
echo "    step_number=1,"
echo "    step_name=\"classify_intent\","
echo "    input=user_message,"
echo "    output=agent_response,"
echo "  )"
echo ""
echo "Dashboard: ${CYAN}https://app.kalytera.dev${RESET}"
echo "Docs:      ${CYAN}https://kalytera.dev${RESET} → Docs"
echo ""
echo "${GREEN}Done.${RESET}"
