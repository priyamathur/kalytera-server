"""
Log parsers for different agent frameworks and export formats
Handles JSON, CSV, and LangSmith exports with proper validation
"""

import json
import csv
import io
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field, validator
# import pandas as pd  # Removed for deployment - using native csv module instead


class ParsedInteraction(BaseModel):
    """Standardized interaction format after parsing"""
    session_id: str
    timestamp: datetime
    user_input: str
    agent_response: str
    workflow_step: int = 1
    tool_calls: Optional[List[str]] = None
    response_time_ms: Optional[int] = None
    tokens_used: Optional[int] = None
    error_occurred: bool = False
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}

    @validator('timestamp', pre=True)
    def parse_timestamp(cls, v):
        if isinstance(v, str):
            # Handle multiple timestamp formats
            formats = [
                '%Y-%m-%dT%H:%M:%S.%fZ',  # ISO with microseconds
                '%Y-%m-%dT%H:%M:%SZ',     # ISO without microseconds
                '%Y-%m-%d %H:%M:%S',      # Standard datetime
                '%m/%d/%Y %H:%M:%S',      # US format
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
            raise ValueError(f"Unable to parse timestamp: {v}")
        return v


class JSONLogParser:
    """Parse JSON log files from various agent frameworks"""
    
    @staticmethod
    def parse_generic_json(data: Union[str, List[Dict], Dict]) -> List[ParsedInteraction]:
        """Parse generic JSON format with flexible schema detection"""
        
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON format: {e}")
        
        # Handle single interaction vs list of interactions
        if isinstance(data, dict):
            data = [data]
        
        interactions = []
        current_session = None
        
        for i, record in enumerate(data):
            try:
                # Auto-detect field mappings
                interaction = JSONLogParser._map_generic_fields(record, i)
                
                # Group by session_id or create sessions
                if not interaction.session_id:
                    if not current_session:
                        current_session = str(uuid.uuid4())
                    interaction.session_id = current_session
                
                interactions.append(interaction)
                
            except Exception as e:
                print(f"⚠️  Skipping malformed record {i}: {e}")
                continue
        
        return interactions
    
    @staticmethod
    def _map_generic_fields(record: Dict[str, Any], step: int) -> ParsedInteraction:
        """Map common field variations to standardized format"""
        
        # Common field name variations
        field_mappings = {
            'session_id': ['session_id', 'sessionId', 'conversation_id', 'thread_id'],
            'timestamp': ['timestamp', 'created_at', 'time', 'datetime', 'date'],
            'user_input': ['user_input', 'human_message', 'query', 'question', 'input', 'user_message'],
            'agent_response': ['agent_response', 'ai_message', 'response', 'answer', 'output', 'assistant_message'],
            'tool_calls': ['tool_calls', 'tools_used', 'functions_called', 'actions'],
            'response_time_ms': ['response_time_ms', 'latency_ms', 'duration_ms', 'elapsed_ms'],
            'tokens_used': ['tokens_used', 'token_count', 'total_tokens'],
            'error_occurred': ['error_occurred', 'has_error', 'error', 'failed'],
            'error_message': ['error_message', 'error_text', 'failure_reason']
        }
        
        mapped = {}
        
        for target_field, possible_names in field_mappings.items():
            for name in possible_names:
                if name in record:
                    mapped[target_field] = record[name]
                    break
        
        # Handle tool_calls as string or list
        if 'tool_calls' in mapped and isinstance(mapped['tool_calls'], str):
            try:
                mapped['tool_calls'] = json.loads(mapped['tool_calls'])
            except:
                mapped['tool_calls'] = [mapped['tool_calls']] if mapped['tool_calls'] else None
        
        # Default values and validation
        return ParsedInteraction(
            session_id=mapped.get('session_id', ''),
            timestamp=mapped.get('timestamp', datetime.now(timezone.utc)),
            user_input=mapped.get('user_input', ''),
            agent_response=mapped.get('agent_response', ''),
            workflow_step=step + 1,
            tool_calls=mapped.get('tool_calls'),
            response_time_ms=mapped.get('response_time_ms'),
            tokens_used=mapped.get('tokens_used'),
            error_occurred=bool(mapped.get('error_occurred', False)),
            error_message=mapped.get('error_message'),
            metadata={k: v for k, v in record.items() if k not in [item for sublist in field_mappings.values() for item in sublist]}
        )


class CSVLogParser:
    """Parse CSV log files with automatic column detection"""
    
    @staticmethod
    def parse_csv(data: Union[str, io.StringIO]) -> List[ParsedInteraction]:
        """Parse CSV data with flexible column mapping"""
        
        if isinstance(data, str):
            data = io.StringIO(data)
        
        # Read CSV with native csv module
        try:
            reader = csv.DictReader(data)
            rows = list(reader)
        except Exception as e:
            raise ValueError(f"Failed to parse CSV: {e}")
        
        if not rows:
            return []
        
        interactions = []
        
        # Auto-detect column mappings
        column_mappings = CSVLogParser._detect_column_mappings(list(rows[0].keys()) if rows else [])
        
        for idx, row in enumerate(rows):
            try:
                interaction = CSVLogParser._map_csv_row(row, column_mappings, idx)
                interactions.append(interaction)
            except Exception as e:
                print(f"⚠️  Skipping malformed CSV row {idx}: {e}")
                continue
        
        return interactions
    
    @staticmethod
    def _detect_column_mappings(columns: List[str]) -> Dict[str, str]:
        """Detect column mappings based on column names"""
        
        mappings = {}
        columns_lower = [col.lower().replace('_', '').replace(' ', '') for col in columns]
        
        field_patterns = {
            'session_id': ['sessionid', 'conversationid', 'threadid'],
            'timestamp': ['timestamp', 'createdat', 'time', 'datetime', 'date'],
            'user_input': ['userinput', 'humanmessage', 'query', 'question', 'input'],
            'agent_response': ['agentresponse', 'aimessage', 'response', 'answer', 'output'],
            'tool_calls': ['toolcalls', 'toolsused', 'functionscalled', 'actions'],
            'response_time_ms': ['responsetimems', 'latencyms', 'durationms', 'elapsedms'],
            'tokens_used': ['tokensused', 'tokencount', 'totaltokens'],
            'error_occurred': ['erroroccurred', 'haserror', 'error', 'failed'],
            'error_message': ['errormessage', 'errortext', 'failurereason']
        }
        
        for target_field, patterns in field_patterns.items():
            for i, col_clean in enumerate(columns_lower):
                if col_clean in patterns or any(pattern in col_clean for pattern in patterns):
                    mappings[target_field] = columns[i]
                    break
        
        return mappings
    
    @staticmethod
    def _map_csv_row(row: pd.Series, mappings: Dict[str, str], step: int) -> ParsedInteraction:
        """Map CSV row to ParsedInteraction"""
        
        mapped = {}
        
        for target_field, column_name in mappings.items():
            if column_name in row.index and pd.notna(row[column_name]):
                mapped[target_field] = row[column_name]
        
        # Handle tool_calls parsing
        if 'tool_calls' in mapped:
            tool_calls_str = str(mapped['tool_calls'])
            try:
                mapped['tool_calls'] = json.loads(tool_calls_str) if tool_calls_str != 'nan' else None
            except:
                mapped['tool_calls'] = [tool_calls_str] if tool_calls_str != 'nan' else None
        
        return ParsedInteraction(
            session_id=mapped.get('session_id', str(uuid.uuid4())),
            timestamp=pd.to_datetime(mapped.get('timestamp', datetime.now(timezone.utc))),
            user_input=str(mapped.get('user_input', '')),
            agent_response=str(mapped.get('agent_response', '')),
            workflow_step=step + 1,
            tool_calls=mapped.get('tool_calls'),
            response_time_ms=int(mapped['response_time_ms']) if 'response_time_ms' in mapped else None,
            tokens_used=int(mapped['tokens_used']) if 'tokens_used' in mapped else None,
            error_occurred=bool(mapped.get('error_occurred', False)),
            error_message=mapped.get('error_message'),
            metadata={col: row[col] for col in row.index if col not in mappings.values() and pd.notna(row[col])}
        )


class LangSmithParser:
    """Parse LangSmith export files for zero adoption friction"""
    
    @staticmethod
    def parse_langsmith_export(data: Union[str, Dict, List[Dict]]) -> List[ParsedInteraction]:
        """Parse LangSmith trace exports"""
        
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid LangSmith JSON: {e}")
        
        if isinstance(data, dict):
            # Single trace
            return LangSmithParser._parse_single_trace(data)
        elif isinstance(data, list):
            # Multiple traces
            interactions = []
            for trace in data:
                interactions.extend(LangSmithParser._parse_single_trace(trace))
            return interactions
        else:
            raise ValueError("Unsupported LangSmith export format")
    
    @staticmethod
    def _parse_single_trace(trace: Dict[str, Any]) -> List[ParsedInteraction]:
        """Parse a single LangSmith trace into interactions"""
        
        interactions = []
        
        # Extract session info
        session_id = trace.get('id', str(uuid.uuid4()))
        
        # Handle different LangSmith export formats
        if 'runs' in trace:
            # New format with runs array
            runs = trace['runs']
        elif 'children' in trace:
            # Nested format
            runs = [trace] + LangSmithParser._extract_nested_runs(trace['children'])
        else:
            # Single run
            runs = [trace]
        
        step = 1
        for run in runs:
            if LangSmithParser._is_chat_interaction(run):
                interaction = LangSmithParser._parse_run_to_interaction(run, session_id, step)
                if interaction:
                    interactions.append(interaction)
                    step += 1
        
        return interactions
    
    @staticmethod
    def _extract_nested_runs(children: List[Dict]) -> List[Dict]:
        """Recursively extract runs from nested structure"""
        runs = []
        for child in children:
            runs.append(child)
            if 'children' in child:
                runs.extend(LangSmithParser._extract_nested_runs(child['children']))
        return runs
    
    @staticmethod
    def _is_chat_interaction(run: Dict[str, Any]) -> bool:
        """Determine if a run represents a user-agent interaction"""
        run_type = run.get('run_type', '')
        name = run.get('name', '').lower()
        
        # Look for chat/conversation indicators
        chat_indicators = ['chat', 'conversation', 'llm', 'agent', 'assistant']
        return (run_type == 'llm' or 
                any(indicator in name for indicator in chat_indicators) or
                ('inputs' in run and 'messages' in run.get('inputs', {})))
    
    @staticmethod
    def _parse_run_to_interaction(run: Dict[str, Any], session_id: str, step: int) -> Optional[ParsedInteraction]:
        """Convert LangSmith run to ParsedInteraction"""
        
        try:
            # Extract inputs
            inputs = run.get('inputs', {})
            user_input = ''
            
            if 'messages' in inputs:
                messages = inputs['messages']
                if isinstance(messages, list) and messages:
                    # Find the last human message
                    for msg in reversed(messages):
                        if isinstance(msg, dict) and msg.get('type') == 'human':
                            user_input = msg.get('content', '')
                            break
                elif isinstance(messages, str):
                    user_input = messages
            elif 'input' in inputs:
                user_input = str(inputs['input'])
            elif 'question' in inputs:
                user_input = str(inputs['question'])
            
            # Extract outputs
            outputs = run.get('outputs', {})
            agent_response = ''
            
            if 'content' in outputs:
                agent_response = str(outputs['content'])
            elif 'answer' in outputs:
                agent_response = str(outputs['answer'])
            elif 'output' in outputs:
                agent_response = str(outputs['output'])
            elif isinstance(outputs, str):
                agent_response = outputs
            
            # Extract timing
            start_time = run.get('start_time')
            end_time = run.get('end_time')
            response_time_ms = None
            
            if start_time and end_time:
                start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                response_time_ms = int((end - start).total_seconds() * 1000)
            
            # Extract tool usage
            tool_calls = None
            if 'extra' in run and 'tool_calls' in run['extra']:
                tool_calls = run['extra']['tool_calls']
            elif 'events' in run:
                # Look for tool events
                tools = []
                for event in run['events']:
                    if event.get('name', '').startswith('tool_'):
                        tools.append(event['name'])
                tool_calls = tools if tools else None
            
            # Extract error info
            error = run.get('error')
            error_occurred = bool(error)
            error_message = str(error) if error else None
            
            # Extract tokens
            tokens_used = None
            if 'extra' in run:
                extra = run['extra']
                if 'usage' in extra:
                    usage = extra['usage']
                    tokens_used = usage.get('total_tokens')
                elif 'total_tokens' in extra:
                    tokens_used = extra['total_tokens']
            
            return ParsedInteraction(
                session_id=session_id,
                timestamp=datetime.fromisoformat(start_time.replace('Z', '+00:00')) if start_time else datetime.now(timezone.utc),
                user_input=user_input,
                agent_response=agent_response,
                workflow_step=step,
                tool_calls=tool_calls,
                response_time_ms=response_time_ms,
                tokens_used=tokens_used,
                error_occurred=error_occurred,
                error_message=error_message,
                metadata={
                    'langsmith_run_id': run.get('id'),
                    'langsmith_run_type': run.get('run_type'),
                    'langsmith_name': run.get('name')
                }
            )
            
        except Exception as e:
            print(f"⚠️  Failed to parse LangSmith run: {e}")
            return None


# Main parser interface
class LogParser:
    """Unified interface for all log parsing"""
    
    @staticmethod
    def parse(data: Union[str, Dict, List], format_type: str = 'auto') -> List[ParsedInteraction]:
        """Parse logs with automatic format detection"""
        
        if format_type == 'auto':
            format_type = LogParser._detect_format(data)
        
        if format_type == 'json':
            return JSONLogParser.parse_generic_json(data)
        elif format_type == 'csv':
            return CSVLogParser.parse_csv(data)
        elif format_type == 'langsmith':
            return LangSmithParser.parse_langsmith_export(data)
        else:
            raise ValueError(f"Unsupported format: {format_type}")
    
    @staticmethod
    def _detect_format(data: Union[str, Dict, List]) -> str:
        """Auto-detect log format"""
        
        if isinstance(data, (dict, list)):
            # Check for LangSmith indicators
            sample = data if isinstance(data, dict) else (data[0] if data else {})
            if any(key in sample for key in ['runs', 'run_type', 'start_time', 'end_time']):
                return 'langsmith'
            return 'json'
        
        if isinstance(data, str):
            data = data.strip()
            if data.startswith(('[', '{')):
                # Looks like JSON, check for LangSmith
                try:
                    parsed = json.loads(data)
                    if isinstance(parsed, dict) and 'runs' in parsed:
                        return 'langsmith'
                    return 'json'
                except:
                    pass
            
            # Check for CSV indicators
            if ',' in data and '\n' in data:
                lines = data.split('\n')
                if len(lines) > 1 and len(lines[0].split(',')) > 2:
                    return 'csv'
        
        return 'json'  # Default fallback