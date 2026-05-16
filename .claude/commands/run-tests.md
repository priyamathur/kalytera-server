# Run Tests

Run the QA agent following rules in .claude/agents/qa-agent.md.

Steps:
1. Run `pytest tests/ --cov=. --cov-report=term-missing`
2. Check coverage thresholds
3. Review all new functions for test coverage
4. Write QA_REPORT.md entry
5. Stop