#!/usr/bin/env python3
"""
Claude Code Session Picker

A wrapper script that reads Claude Code session files, uses AI to summarize each chat,
and provides an interactive interface to select and launch sessions.

Features:x
- First-time setup to configure your Claude Code directories
- Automatic detection of session files
- AI-powered session summaries using Claude CLI
- Interactive session selection and launching
- Caching of summaries for faster subsequent runs
- Cleanup of empty sessions

Requirements:
- Python 3.6+
- Claude CLI (pip install claude-cli)
- Claude Code sessions (.jsonl files)

Usage: 
    python3 claude-session-picker.py

First Run:
- The script will guide you through configuration setup
- It will detect your Claude directories or let you specify custom paths
- Configuration is saved to OS-appropriate config directory using platformdirs
"""

import os
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Union
from datetime import datetime
import tempfile
import re
import textwrap
from platformdirs import user_config_dir
from tabulate import tabulate
from colorama import init, Fore, Style

# Initialize colorama for cross-platform colored output
init(autoreset=True)

# JSON key constants
TYPE_KEY = 'type'
MESSAGE_KEY = 'message'
CONTENT_KEY = 'content'
SUMMARY_KEY = 'summary'
TEXT_KEY = 'text'
TOOL_USE_KEY = 'tool_use'
NAME_KEY = 'name'
INPUT_KEY = 'input'

# Message types
USER_TYPE = 'user'
ASSISTANT_TYPE = 'assistant'
SUMMARY_TYPE = 'summary'

# Configuration - will be set by setup process
CLAUDE_PROJECTS_DIR = None
SESSION_SUMMARIES_DIR = None
MAX_CONTENT_LENGTH = 20000  # Limit content sent for summarization
CONFIG_PATH = Path(user_config_dir("claude-session-picker")) / "config.json"


class SessionFile:
    """Represents a Claude Code session file"""
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.modified_time = file_path.stat().st_mtime
        self.size = file_path.stat().st_size
        self.project_dir = file_path.parent.name
        self.project_dir_full_path = file_path.parent  # Store the full path
        self.session_id = file_path.stem
        self.conversations = []
        self.summary = ""
        self.message_count = 0
        self.is_continuation = False
        self.continued_from_session = None
        
    def load_conversations(self) -> List[Dict]:
        """Load and parse conversation data from the JSONL file"""
        conversations = []
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            conversations.append(data)
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            print(f"Error reading {self.file_path}: {e}")
        
        self.conversations = conversations
        
        # Check if this is a continuation session
        sidechain_messages = [conv for conv in conversations if conv.get('isSidechain', False)]
        if sidechain_messages:
            self.is_continuation = True
        
        # Also check for continuation pattern in messages
        if not self.is_continuation:
            for conv in conversations:
                # Check user messages for continuation pattern
                if conv.get('type') == 'user':
                    message = conv.get('message', {})
                    content = message.get('content', '')
                    if isinstance(content, str) and 'This session is being continued from' in content:
                        self.is_continuation = True
                        # Extract session ID if mentioned
                        import re
                        session_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', content)
                        if session_match:
                            self.continued_from_session = session_match.group(1)
                        break
        
        # Count only user messages - exclude sidechain (continued) messages and tool results
        user_messages = []
        for conv in conversations:
            if conv.get('type') == 'user' and not conv.get('isSidechain', False):
                message = conv.get('message', {})
                content = message.get('content', '')
                # Skip tool result messages (they start with array of tool results)
                if isinstance(content, str) and not content.strip().startswith('[{"tool_use_id"'):
                    user_messages.append(conv)
        self.message_count = len(user_messages)
        return conversations
    
    def extract_content_for_summary(self) -> str:
        """Extract key topics and actions for AI summarization - prioritize user messages"""
        
        # Look for existing summary entries but only use if they're descriptive
        summaries = [conv.get('summary', '') for conv in self.conversations
                    if conv.get('type') == 'summary' and conv.get('summary')]
        
        # Skip generic/short summaries - only use if they're descriptive enough
        good_summaries = [s for s in summaries if len(s) > 50 and not any(generic in s.lower() for generic in ['config', 'path', 'picker', 'session', 'claude code'])]
        if good_summaries:
            return ' | '.join(good_summaries[:3])  # Use only good existing summaries
        
        # Smart extraction - use same logic as message counter to find real user messages
        user_messages = []
        for conv in self.conversations:
            if conv.get('type') == 'user' and not conv.get('isSidechain', False):
                message = conv.get('message', {})
                content = message.get('content', '')
                # Skip tool result messages (they start with array of tool results)
                if isinstance(content, str) and not content.strip().startswith('[{"tool_use_id"'):
                    user_messages.append(conv)
        
        # Select key user messages: first 2, last 2, and 2 from middle
        total_user_msgs = len(user_messages)
        if total_user_msgs <= 6:
            priority_user_messages = user_messages
        else:
            # Take first 2, last 2, and 2 from middle
            first_two = user_messages[:2]
            last_two = user_messages[-2:]
            # Take 2 messages from around the middle
            mid_point = total_user_msgs // 2
            middle_two = user_messages[mid_point - 1 : mid_point + 1] if mid_point > 1 else []
            priority_user_messages = first_two + middle_two + last_two

        priority_conversations = [
            conv for conv in self.conversations if not conv.get("isSidechain", False)
        ]
        
        # Step 1: Extract user requests - take first 200 chars of each message
        user_requests = []
        for conv in priority_user_messages:
            message = conv.get('message', {})
            content = message.get('content', '')
            if isinstance(content, str) and content.strip():
                cleaned_content = content.strip()
                # Skip very short messages like "ok", "yes", "thanks"
                if len(cleaned_content) > 10:
                    # Focus on the action - take first 200 chars which usually contain the main request
                    action_focused = cleaned_content[:200]
                    user_requests.append(action_focused)
        
        # Step 2: If user messages provide enough context (>200 chars), use only those
        user_context = ' | '.join(user_requests)
        if len(user_context) > 200:
            return user_context
        
        # Step 3: If not enough user context, add assistant actions and tool uses
        assistant_actions = []
        tool_uses = []
        
        for conv in priority_conversations:
            if conv.get('type') == 'assistant' and not conv.get('isSidechain', False):
                message = conv.get('message', {})
                content = message.get('content', [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            if item.get('type') == 'text':
                                text = item.get('text', '')
                                # Look for action words/key phrases
                                if any(word in text.lower() for word in ['create', 'update', 'fix', 'add', 'remove', 'install', 'configure', 'debug', 'implement']):
                                    assistant_actions.append(text[:150])
                            elif item.get('type') == 'tool_use':
                                tool_name = item.get('name', '')
                                tool_input = item.get('input', {})
                                if tool_name and tool_input:
                                    # Enhanced parsing for official Claude Code tools
                                    desc_parts = []
                                    # Core file tools
                                    if tool_name == 'Read' and 'file_path' in tool_input:
                                        desc_parts.append(f"read: {tool_input['file_path']}")
                                    elif tool_name in ['Edit', 'MultiEdit'] and 'file_path' in tool_input:
                                        desc_parts.append(f"edited: {tool_input['file_path']}")
                                    elif tool_name == 'Write' and 'file_path' in tool_input:
                                        desc_parts.append(f"wrote: {tool_input['file_path']}")
                                    # Terminal tools
                                    elif tool_name == 'Bash' and 'command' in tool_input:
                                        desc_parts.append(f"ran: {tool_input['command'][:70]}")
                                    # Search tools
                                    elif tool_name in ['LS', 'Glob', 'Grep'] and 'path' in tool_input:
                                        desc_parts.append(f"searched: {tool_input['path']}")
                                    elif tool_name == 'Grep' and 'pattern' in tool_input:
                                        desc_parts.append(f"grepped: {tool_input['pattern']}")
                                    # Notebook tools
                                    elif tool_name in ['NotebookRead', 'NotebookEdit'] and 'notebook_path' in tool_input:
                                        desc_parts.append(f"notebook: {tool_input['notebook_path']}")
                                    # Todo tools
                                    elif tool_name in ['TodoRead', 'TodoWrite']:
                                        desc_parts.append("managed todos")
                                    # Web tools
                                    elif tool_name in ['WebFetch', 'WebSearch'] and 'url' in tool_input:
                                        desc_parts.append(f"web: {tool_input['url']}")
                                    elif tool_name == 'WebSearch' and 'query' in tool_input:
                                        desc_parts.append(f"searched: {tool_input['query']}")
                                    # Fallback to common fields
                                    elif 'description' in tool_input:
                                        desc_parts.append(tool_input['description'][:70])
                                    elif 'command' in tool_input:
                                        desc_parts.append(tool_input['command'][:70])
                                    
                                    if desc_parts:
                                        tool_uses.append(f"Tool '{tool_name}': {desc_parts[0]}")
                                    else:
                                        tool_uses.append(f"Tool '{tool_name}': {str(tool_input)[:70]}")
        
        # Combine the most relevant parts
        summary_parts = []
        if user_requests:
            summary_parts.extend(f"User: {req}" for req in user_requests[:3])
        if assistant_actions:
            summary_parts.extend(f"Action: {action}" for action in assistant_actions[:2])
        if tool_uses:
            summary_parts.extend(f"Tool: {tool}" for tool in tool_uses[:2])
        
        # If no smart content found, fall back to basic extraction
        if not summary_parts:
            for conv in self.conversations[:5]:  # Just first 5 messages
                if conv.get('type') == 'user' and not conv.get('isSidechain', False):
                    content = conv.get('message', {}).get('content', '')
                    if isinstance(content, str) and content.strip():
                        # Skip tool result messages
                        if not content.strip().startswith('[{"tool_use_id"'):
                            summary_parts.append(f"User: {content[:100]}")
        
        result = ' | '.join(summary_parts)
        if len(result) > MAX_CONTENT_LENGTH:
            result = result[:MAX_CONTENT_LENGTH] + "..."
        
        return result or "Empty conversation"


def decode_project_path(encoded_name: str) -> str:
    """Decode the project directory name back to actual file path"""
    username = os.getenv('USER', 'user')
    
    # Handle the encoded format: -Users-username-Desktop-project-name
    # This format uses - as path separator
    if encoded_name.startswith('-Users-'):
        # Split by - and reconstruct the path
        parts = encoded_name.split('-')
        # Remove empty first element from leading -
        if parts[0] == '':
            parts = parts[1:]
        # Reconstruct as actual path
        return '/' + '/'.join(parts)
    else:
        # If it doesn't match expected format, return as-is
        return encoded_name


def find_project_directories() -> List[Path]:
    """Find all project directories"""
    project_dirs = []
    
    if not CLAUDE_PROJECTS_DIR or not CLAUDE_PROJECTS_DIR.exists():
        print(f"Claude projects directory not found: {CLAUDE_PROJECTS_DIR}")
        return project_dirs
    
    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if project_dir.is_dir() and not project_dir.name.startswith('.'):
            # Check if directory contains .jsonl files
            if any(project_dir.glob("*.jsonl")):
                project_dirs.append(project_dir)
    
    # Sort by modification time (newest first)
    project_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return project_dirs


def find_session_files_in_project(project_dir: Path) -> List[SessionFile]:
    """Find all .jsonl session files in a specific project directory"""
    session_files = []
    
    for jsonl_file in project_dir.glob("*.jsonl"):
        if jsonl_file.is_file():
            session_files.append(SessionFile(jsonl_file))
    
    # Sort by modification time (newest first)
    session_files.sort(key=lambda x: x.modified_time, reverse=True)
    return session_files


def get_cache_file_path(project_dir: Path) -> Path:
    """Get the cache file path for a specific project"""
    cache_filename = f"CACHE: {project_dir.name}.json"
    return SESSION_SUMMARIES_DIR / cache_filename


def load_cache_for_project(project_dir: Path) -> Dict:
    """Load summary cache for a specific project from disk"""
    cache_file = get_cache_file_path(project_dir)
    try:
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except json.JSONDecodeError:
        print(f"{Fore.YELLOW}Warning: Cache file corrupted for {project_dir.name}. Ignoring cache.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}Warning: Could not load cache for {project_dir.name}: {e}{Style.RESET_ALL}")
    return {}


def save_cache_for_project(project_dir: Path, cache: Dict) -> None:
    """Save summary cache for a specific project to disk"""
    try:
        SESSION_SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = get_cache_file_path(project_dir)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save cache for {project_dir.name}: {e}")


def get_cached_summary(session: SessionFile, cache: Dict) -> str:
    """Get cached summary if it exists and is still valid"""
    file_key = str(session.file_path)
    if file_key in cache:
        cached_data = cache[file_key]
        # Check if cached summary is still valid (file hasn't been modified)
        if cached_data.get('modified_time') == session.modified_time:
            # Also restore the message count and continuation info from cache
            session.message_count = cached_data.get('message_count', 0)
            session.is_continuation = cached_data.get('is_continuation', False)
            session.continued_from_session = cached_data.get('continued_from_session', None)
            return cached_data.get('summary', '')
    return None


def cache_summary(session: SessionFile, summary: str, cache: Dict) -> None:
    """Cache a summary for a session"""
    file_key = str(session.file_path)
    cache[file_key] = {
        'summary': summary,
        'modified_time': session.modified_time,
        'session_id': session.session_id,
        'project_dir': session.project_dir,
        'message_count': session.message_count,
        'is_continuation': session.is_continuation,
        'continued_from_session': session.continued_from_session
    }


def summarize_with_claude(content: str) -> str:
    """Use Claude CLI to summarize the conversation content"""
    if not content or content.strip() == "Empty conversation":
        return "Empty or unreadable conversation"
    
    prompt = f"""Summarize what was accomplished in this Claude Code session. Format your response as bullet points using numbered format.

Focus on key actions taken, operations performed, or significant tools used.
Provide 2-3 brief numbered bullet points. Each bullet point should be 3-5 words only.
Use numbered bullet point format with each point on a separate line.
Start directly with the numbered points - no preamble text.
Use plain text only - no markdown formatting, no bold, no italics, no asterisks.

Session Activities:
{content}"""
    
    try:
        # Use Claude CLI in single prompt mode
        result = subprocess.run([
            'claude',
            '-p', prompt
        ], capture_output=True, text=True, timeout=45)
        
        if result.returncode == 0:
            summary = result.stdout.strip()
            # Strip preamble text - look for pattern ending with numbered list
            # If summary contains numbered points, extract just the numbered portion
            if re.search(r'\d+\.', summary):
                # Find the start of the numbered list
                numbered_match = re.search(r'(\d+\.\s+.*)', summary, re.DOTALL)
                if numbered_match:
                    summary = numbered_match.group(1)
            
            # Further cleanup: remove leading asterisks or dashes if they are part of the text from Claude
            summary = re.sub(r"^\s*[\*\-]\s*", "", summary)  # Remove leading bullet point character if present
            
            # Remove markdown formatting (bold, italic, etc.)
            summary = re.sub(r'\*\*(.*?)\*\*', r'\1', summary)  # Remove **bold** formatting
            summary = re.sub(r'\*(.*?)\*', r'\1', summary)      # Remove *italic* formatting
            
            # 🔽 NEW: force each "1." "2." … onto its own line
            summary = re.sub(r'\s*(\d+\.)\s+', r'\n\1 ', summary).lstrip('\n')
            
            # Clean up extra spaces
            summary = re.sub(r" {2,}", " ", summary).strip()
            return summary[:400] if summary else "Unable to generate summary (empty response)"
        else:
            return f"CLI error: {result.stderr[:50]}"
            
    except subprocess.TimeoutExpired:
        return "Summary generation timed out"
    except FileNotFoundError:
        return "Claude CLI not found - install claude-cli"
    except Exception as e:
        return f"Error: {str(e)[:50]}"


def display_project_directories(project_dirs: List[Path]) -> None:
    """Display available project directories in professional table format"""
    from datetime import datetime
    
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}SELECT PROJECT DIRECTORY")
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    
    # Prepare table data
    table_data = []
    headers = ["#", "Project Name", "Sessions", "Last Modified"]
    
    for i, project_dir in enumerate(project_dirs, 1):
        modified_time = project_dir.stat().st_mtime
        modified_str = datetime.fromtimestamp(modified_time).strftime("%b %d, %Y at %I:%M %p")
        
        # Count session files
        session_count = len(list(project_dir.glob("*.jsonl")))
        
        # Clean up project name for display
        display_name = decode_project_path(project_dir.name)
        # Remove /Users/username prefix for cleaner display
        username = os.getenv('USER', 'user')
        home_prefix = f'/Users/{username}/'
        if display_name.startswith(home_prefix):
            display_name = '~/' + display_name[len(home_prefix):]
        
        # Truncate very long project names
        if len(display_name) > 40:
            display_name = display_name[:37] + "..."
        
        # Color the row number and session count
        row_num = f"{Fore.YELLOW}{i}{Style.RESET_ALL}"
        session_display = f"{Fore.GREEN}{session_count}{Style.RESET_ALL} session{'s' if session_count != 1 else ''}"
        
        table_data.append([
            row_num,
            display_name,
            session_display,
            modified_str
        ])
    
    # Print the table with professional formatting
    print(tabulate(
        table_data,
        headers=[f"{Fore.CYAN}{h}{Style.RESET_ALL}" for h in headers],
        tablefmt="fancy_grid",
        colalign=["center", "left", "right", "left"]
    ))


def get_project_selection(project_dirs: List[Path]) -> Path:
    """Get user's project directory selection"""
    while True:
        try:
            choice = input(f"\nSelect project (1-{len(project_dirs)}) or 'q' to quit: ").strip()
            
            if choice.lower() == 'q':
                print("Goodbye!")
                sys.exit(0)
            
            index = int(choice) - 1
            if 0 <= index < len(project_dirs):
                return project_dirs[index]
            else:
                print(f"Please enter a number between 1 and {len(project_dirs)}")
                
        except ValueError:
            print("Please enter a valid number or 'q' to quit")
        except KeyboardInterrupt:
            print("\nGoodbye!")
            sys.exit(0)


def display_sessions(sessions: List[SessionFile], project_name: str) -> None:
    """Display sessions with summaries in professional table format"""
    from datetime import datetime
    
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}CLAUDE CODE SESSION PICKER - {project_name}")
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    
    if not sessions:
        print("No sessions found in this project.")
        return
    
    # Prepare table data
    table_data = []
    headers = ["#", "Date", "Msgs", "Summary"]
    
    for i, session in enumerate(sessions, 1):
        modified_time = datetime.fromtimestamp(session.modified_time)
        date_str = modified_time.strftime("%b %d")
        time_str = modified_time.strftime("%I:%M %p")
        datetime_str = f"{date_str}\n{time_str}"
        
        # Truncate session ID for display
        session_id_display = session.session_id[:12] + "..." if len(session.session_id) > 15 else session.session_id
        
        # Use full summary and add session ID at bottom with simple line breaks
        # Add newline every 50 characters
        summary_text = session.summary
        wrapped_lines = []
        for line in summary_text.split('\n'):
            if len(line) <= 50:
                wrapped_lines.append(line)
            else:
                # Split long lines every 50 characters
                for j in range(0, len(line), 50):
                    wrapped_lines.append(line[j:j+50])
        
        wrapped_summary = '\n'.join(wrapped_lines)
        
        # Add continuation info if applicable
        footer_parts = []
        if session.is_continuation:
            if session.continued_from_session:
                footer_parts.append(f"Continued from: {session.continued_from_session[:8]}...")
            else:
                footer_parts.append("Continued from previous session")
        footer_parts.append(session.session_id)
        
        summary_display = f"{wrapped_summary}\n\n{chr(10).join(footer_parts)}"
        
        # Color the row number
        row_num = f"{Fore.YELLOW}{i}{Style.RESET_ALL}"
        msg_count = f"{Fore.GREEN}{session.message_count}{Style.RESET_ALL}"
        
        table_data.append([
            row_num,
            datetime_str,
            msg_count,
            summary_display
        ])
    
    # Print the table with professional formatting
    print(tabulate(
        table_data,
        headers=[f"{Fore.CYAN}{h}{Style.RESET_ALL}" for h in headers],
        tablefmt="fancy_grid",
        colalign=["center", "center", "center", "left"]
    ))
    print()  # Add spacing after table


def get_session_selection(sessions: List[SessionFile]) -> Union[SessionFile, str, None]:
    """Get user's session selection"""
    while True:
        try:
            choice = input(f"\nSelect session (1-{len(sessions)}) • 'r' re-cache • 'p' previous • 'q' quit: ").strip().lower()
            
            if choice == 'q':
                print("Goodbye!")
                sys.exit(0)
            if choice == 'p':
                return None
            if choice == 'r':
                return 'recache'
            
            index = int(choice) - 1
            if 0 <= index < len(sessions):
                return sessions[index]
            else:
                print(f"Please enter a number between 1 and {len(sessions)}, 'r', 'p', or 'q'")
                
        except ValueError:
            print("Please enter a valid number, 'r', 'p', or 'q'")
        except KeyboardInterrupt:
            print("\nGoodbye!")
            sys.exit(0)


def recache_sessions(sessions: List[SessionFile], cache: Dict) -> bool:
    """Handle re-caching of sessions with user selection"""
    print(f"\n{Fore.CYAN}Re-cache Session Summaries{Style.RESET_ALL}")
    print("Choose which sessions to re-generate summaries for:")
    print(f"  {Fore.YELLOW}all{Style.RESET_ALL} - Re-cache all sessions")
    
    for i, session in enumerate(sessions, 1):
        session_id_display = session.session_id[:12] + "..." if len(session.session_id) > 15 else session.session_id
        print(f"  {Fore.YELLOW}{i}{Style.RESET_ALL} - {session_id_display}")
    
    while True:
        choice = input(f"\nEnter 'all' or session numbers (e.g., '1,3,5') or 'c' to cancel: ").strip().lower()
        
        if choice == 'c':
            return False
        
        sessions_to_recache = []
        
        if choice == 'all':
            sessions_to_recache = sessions
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(',')]
                if all(0 <= i < len(sessions) for i in indices):
                    sessions_to_recache = [sessions[i] for i in indices]
                else:
                    print(f"Please enter valid session numbers between 1 and {len(sessions)}")
                    continue
            except ValueError:
                print("Please enter 'all', valid numbers separated by commas, or 'c' to cancel")
                continue
        
        # Perform re-caching
        print(f"\n{Fore.BLUE}Re-caching {len(sessions_to_recache)} session(s)...{Style.RESET_ALL}")
        for i, session in enumerate(sessions_to_recache, 1):
            print(f"Re-processing session {i}/{len(sessions_to_recache)} ({session.session_id[:8]}...)...", end='', flush=True)
            
            # Force reload conversations and regenerate summary
            session.load_conversations()
            content = session.extract_content_for_summary()
            session.summary = summarize_with_claude(content)
            
            # Update cache
            cache_summary(session, session.summary, cache)
            print(f" {Fore.GREEN}✓{Style.RESET_ALL}")
        
        print(f"\n{Fore.GREEN}Re-caching complete!{Style.RESET_ALL}")
        return True


def delete_empty_sessions(sessions: List[SessionFile], project_dir: Path, cache: Dict) -> Tuple[List[SessionFile], Dict]:
    """Identify and optionally delete sessions with 0 messages"""
    from datetime import datetime
    
    empty_sessions = [session for session in sessions if session.message_count == 0]
    
    if not empty_sessions:
        return sessions, cache
    
    print(f"\nFound {len(empty_sessions)} session(s) with 0 messages:")
    for i, session in enumerate(empty_sessions, 1):
        modified_time = datetime.fromtimestamp(session.modified_time)
        date_str = modified_time.strftime("%b %d, %I:%M %p")
        print(f"  {i}. {date_str} - {session.session_id}")
    
    while True:
        choice = input(f"\nDelete these {len(empty_sessions)} empty session(s)? (y/n): ").strip().lower()
        if choice in ['y', 'yes']:
            deleted_count = 0
            for session in empty_sessions:
                try:
                    session.file_path.unlink()  # Delete the file
                    # Remove from cache
                    file_key = str(session.file_path)
                    if file_key in cache:
                        del cache[file_key]
                    print(f"Deleted: {session.session_id}")
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting {session.session_id}: {e}")
            
            print(f"Successfully deleted {deleted_count} empty session(s)")
            # Return list without deleted sessions and updated cache
            remaining_sessions = [session for session in sessions if session.message_count > 0]
            return remaining_sessions, cache
            
        elif choice in ['n', 'no']:
            print("Keeping empty sessions")
            return sessions, cache
        else:
            print("Please enter 'y' or 'n'")


def launch_session(session: SessionFile) -> None:
    """Launch Claude Code with the selected session"""
    try:
        # Get the actual project path from the encoded name
        actual_project_path = decode_project_path(session.project_dir)
        
        # Clean the session ID - remove any extra whitespace or characters
        clean_session_id = session.session_id.strip()
        
        print(f"\nLaunching Claude Code session in: {actual_project_path}")
        print(f"Session ID: '{clean_session_id}'")
        
        # Check if the directory exists
        project_path_obj = Path(actual_project_path)
        if not project_path_obj.exists():
            print(f"Warning: Project directory doesn't exist: {actual_project_path}")
            print("Launching without changing directory...")
            # Launch without changing directory
            subprocess.run([
                'claude',
                '-r', clean_session_id
            ])
        else:
            # Launch claude with -r flag in the actual project directory
            subprocess.run([
                'claude',
                '-r', clean_session_id
            ], cwd=actual_project_path)
        
    except Exception as e:
        print(f"Error launching session: {e}")
        print(f"Try manually running: claude -r '{clean_session_id}'")
        if 'actual_project_path' in locals():
            print(f"Expected directory: {actual_project_path}")


def load_config() -> bool:
    """Load configuration from file or set up for first time"""
    global CLAUDE_PROJECTS_DIR, SESSION_SUMMARIES_DIR
    
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                CLAUDE_PROJECTS_DIR = Path(config['claude_projects_dir'])
                SESSION_SUMMARIES_DIR = Path(config['session_summaries_dir'])
                
                # Validate paths still exist
                if not CLAUDE_PROJECTS_DIR.exists():
                    print(f"Warning: Claude projects directory no longer exists: {CLAUDE_PROJECTS_DIR}")
                    return setup_configuration()
                    
                return True
        except Exception as e:
            print(f"Error loading config: {e}")
            return setup_configuration()
    else:
        return setup_configuration()


def setup_configuration() -> bool:
    """First-time setup to configure paths"""
    global CLAUDE_PROJECTS_DIR, SESSION_SUMMARIES_DIR
    
    print("=" * 60)
    print("CLAUDE SESSION PICKER - FIRST TIME SETUP")
    print("=" * 60)
    print("Welcome! Let's configure the paths for your Claude Code sessions.\n")
    
    # Default paths
    default_claude_dir = Path.home() / ".claude"
    default_projects_dir = default_claude_dir / "projects"
    default_summaries_dir = default_claude_dir / "Session Summaries"
    
    print(f"Default Claude directory: {default_claude_dir}")
    print(f"Default projects directory: {default_projects_dir}")
    print(f"Default summaries directory: {default_summaries_dir}\n")
    
    # Check if defaults exist
    if default_projects_dir.exists():
        print("✓ Found default Claude projects directory!")
        use_default = input("Use default paths? (y/n): ").strip().lower()
        if use_default in ['y', 'yes', '']:
            CLAUDE_PROJECTS_DIR = default_projects_dir
            SESSION_SUMMARIES_DIR = default_summaries_dir
        else:
            if not get_custom_paths():
                return False
    else:
        print("Default Claude projects directory not found.")
        print("Please specify your Claude Code setup:\n")
        if not get_custom_paths():
            return False
    
    # Create session summaries directory if it doesn't exist
    try:
        SESSION_SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
        print(f"✓ Session summaries directory ready: {SESSION_SUMMARIES_DIR}")
    except Exception as e:
        print(f"Error creating summaries directory: {e}")
        return False
    
    # Save configuration
    try:
        # Ensure config directory exists
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        config = {
            'claude_projects_dir': str(CLAUDE_PROJECTS_DIR),
            'session_summaries_dir': str(SESSION_SUMMARIES_DIR)
        }
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"✓ Configuration saved to: {CONFIG_PATH}")
    except Exception as e:
        print(f"Error saving configuration: {e}")
        return False
    
    print("\nSetup complete! You can now use the session picker.")
    return True


def get_custom_paths() -> bool:
    """Get custom paths from user input"""
    global CLAUDE_PROJECTS_DIR, SESSION_SUMMARIES_DIR
    
    while True:
        projects_path = input("Enter path to Claude projects directory: ").strip()
        if not projects_path:
            print("Path cannot be empty.")
            continue
            
        projects_dir = Path(projects_path).expanduser()
        if not projects_dir.exists():
            print(f"Directory doesn't exist: {projects_dir}")
            create = input("Create it? (y/n): ").strip().lower()
            if create in ['y', 'yes']:
                try:
                    projects_dir.mkdir(parents=True, exist_ok=True)
                    break
                except Exception as e:
                    print(f"Error creating directory: {e}")
                    continue
            else:
                continue
        else:
            break
    
    CLAUDE_PROJECTS_DIR = projects_dir
    
    # Session summaries directory
    default_summaries = projects_dir.parent / "Session Summaries"
    summaries_path = input(f"Session summaries directory [{default_summaries}]: ").strip()
    
    if not summaries_path:
        SESSION_SUMMARIES_DIR = default_summaries
    else:
        SESSION_SUMMARIES_DIR = Path(summaries_path).expanduser()
    
    return True


def check_claude_cli() -> bool:
    """Check if Claude CLI is available"""
    try:
        result = subprocess.run(['claude', '--version'],
                              capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def main():
    """Main function"""
    # Load or setup configuration
    if not load_config():
        print("Configuration setup failed. Exiting.")
        return
    
    # Check if Claude CLI is available
    if not check_claude_cli():
        print("\n⚠️  Warning: Claude CLI not found!")
        print("This script requires the Claude CLI to be installed.")
        print("Install it with: pip install claude-cli")
        print("\nContinuing anyway (session launching will fail)...\n")
    
    while True:
        print("Finding Claude Code projects...")
        project_dirs = find_project_directories()
        
        if not project_dirs:
            print("No Claude Code projects with sessions found!")
            print(f"Make sure your projects directory contains .jsonl files: {CLAUDE_PROJECTS_DIR}")
            return
        
        # Step 1: Display and select project directory
        display_project_directories(project_dirs)
        selected_project = get_project_selection(project_dirs)
        
        while True:
            # Step 2: Find sessions in the selected project
            print(f"\nFinding sessions in {selected_project.name}...")
            sessions = find_session_files_in_project(selected_project)
            
            if not sessions:
                print("No session files found in this project!")
                break
            
            print(f"Found {len(sessions)} sessions. Loading summaries...")
            
            # Load cache for this specific project
            cache = load_cache_for_project(selected_project)
            cache_updated = False
            
            # Generate summaries for each session (use cache when possible)
            for i, session in enumerate(sessions, 1):
                print(f"Processing session {i}/{len(sessions)}...", end='', flush=True)
                
                # Try to get cached summary first
                cached_summary = get_cached_summary(session, cache)
                if cached_summary:
                    session.summary = cached_summary
                    print(f" {Fore.GREEN}(cached) ✓{Style.RESET_ALL}")
                else:
                    # Load conversations and generate new summary
                    session.load_conversations()
                    content = session.extract_content_for_summary()
                    session.summary = summarize_with_claude(content)
                    # Cache the new summary
                    cache_summary(session, session.summary, cache)
                    cache_updated = True
                    print(f" {Fore.BLUE}(new) ✓{Style.RESET_ALL}")
            
            # Always save cache after processing
            save_cache_for_project(selected_project, cache)
            
            # Check for and optionally delete empty sessions
            sessions, cache = delete_empty_sessions(sessions, selected_project, cache)
            
            # Save cache again after potential deletions
            save_cache_for_project(selected_project, cache)
            
            if not sessions:
                print("No sessions remaining after cleanup!")
                break
            
            # Step 3: Display sessions and get user selection
            display_name = decode_project_path(selected_project.name)
            # Shorten for display
            username = os.getenv('USER', 'user')
            home_prefix = f'/Users/{username}/'
            if display_name.startswith(home_prefix):
                display_name = '~/' + display_name[len(home_prefix):]
            
            display_sessions(sessions, display_name)
            selected_session = get_session_selection(sessions)
            
            if selected_session is None:
                # User pressed 'p' to go back to project selection
                break
            elif selected_session == 'recache':
                # User pressed 'r' to re-cache sessions
                if recache_sessions(sessions, cache):
                    # Save updated cache after re-caching
                    save_cache_for_project(selected_project, cache)
                # Continue the loop to show updated sessions
                continue
            
            # Launch the selected session
            launch_session(selected_session)
            return  # Exit after launching session


if __name__ == "__main__":
    main()
