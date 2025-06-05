#!/usr/bin/env python3
"""
Claude Code Session Picker

A wrapper script that reads Claude Code session files, uses AI to summarize each chat,
and provides an interactive interface to select and launch sessions.

Features:
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
from typing import List, Dict, Tuple
from datetime import datetime
import tempfile
from platformdirs import user_config_dir
from tabulate import tabulate
from colorama import init, Fore, Style

# Initialize colorama for cross-platform colored output
init(autoreset=True)

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
        self.session_id = file_path.stem
        self.conversations = []
        self.summary = ""
        self.message_count = 0
        
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
        # Count messages (user and assistant types)
        self.message_count = len([conv for conv in conversations if conv.get('type') in ['user', 'assistant']])
        return conversations
    
    def extract_content_for_summary(self) -> str:
        """Extract key topics and actions for AI summarization"""
        content_parts = []
        
        # Look for existing summary entries but only use if they're descriptive
        summaries = [conv.get('summary', '') for conv in self.conversations
                    if conv.get('type') == 'summary' and conv.get('summary')]
        
        # Skip generic/short summaries - only use if they're descriptive enough
        good_summaries = [s for s in summaries if len(s) > 50 and not any(generic in s.lower() for generic in ['config', 'path', 'picker', 'session', 'claude code'])]
        if good_summaries:
            return ' | '.join(good_summaries[:3])  # Use only good existing summaries
        
        # Smart extraction - focus on key patterns
        user_requests = []
        assistant_actions = []
        tool_uses = []
        
        for conv in self.conversations:
            if conv.get('type') == 'user':
                message = conv.get('message', {})
                content = message.get('content', '')
                if isinstance(content, str) and content.strip():
                    # Extract user requests/questions (first sentence or up to 100 chars)
                    first_sentence = content.split('.')[0].split('?')[0].split('!')[0]
                    user_requests.append(first_sentence[:100])
                    
            elif conv.get('type') == 'assistant':
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
                                    # Capture what tools were used
                                    desc = tool_input.get('description', tool_input.get('command', ''))
                                    tool_uses.append(f"{tool_name}: {desc[:100]}")
        
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
                if conv.get('type') == 'user':
                    content = conv.get('message', {}).get('content', '')
                    if isinstance(content, str) and content.strip():
                        summary_parts.append(f"User: {content[:100]}")
        
        result = ' | '.join(summary_parts)
        if len(result) > MAX_CONTENT_LENGTH:
            result = result[:MAX_CONTENT_LENGTH] + "..."
        
        return result or "Empty conversation"


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
    except Exception as e:
        print(f"Warning: Could not load cache for {project_dir.name}: {e}")
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
            # Also restore the message count from cache
            session.message_count = cached_data.get('message_count', 0)
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
        'message_count': session.message_count
    }


def summarize_with_claude(content: str) -> str:
    """Use Claude CLI to summarize the conversation content"""
    if not content or content.strip() == "Empty conversation":
        return "Empty or unreadable conversation"
    
    prompt = f"""Summarize this Claude Code conversation as 2-3 short bullet points (each 3-8 words), focusing on the main tasks or topics:

{content}

Format as bullet points separated by periods. Example: "Created Python script. Fixed API errors. Added caching system."

Summary:"""
    
    try:
        # Use Claude CLI in single prompt mode
        result = subprocess.run([
            'claude',
            '-p', prompt
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            summary = result.stdout.strip()
            # Clean up the summary
            if summary.startswith("Summary:"):
                summary = summary[8:].strip()
            return summary[:150] if summary else "Unable to generate summary"
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
        display_name = project_dir.name
        username = os.getenv('USER', 'user')
        user_prefix = f'-Users-{username}-'
        if display_name.startswith(user_prefix):
            display_name = display_name.replace(user_prefix, '').replace('-', '/')
        
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
    headers = ["#", "Date", "Time", "Messages", "Session ID", "Summary"]
    
    for i, session in enumerate(sessions, 1):
        modified_time = datetime.fromtimestamp(session.modified_time)
        date_str = modified_time.strftime("%b %d")
        time_str = modified_time.strftime("%I:%M %p")
        
        # Truncate session ID for display
        session_id_display = session.session_id[:12] + "..." if len(session.session_id) > 15 else session.session_id
        
        # Use full summary without truncation
        summary_display = session.summary
        
        # Color the row number
        row_num = f"{Fore.YELLOW}{i}{Style.RESET_ALL}"
        msg_count = f"{Fore.GREEN}{session.message_count}{Style.RESET_ALL}"
        
        table_data.append([
            row_num,
            date_str,
            time_str,
            msg_count,
            session_id_display,
            summary_display
        ])
    
    # Print the table with professional formatting
    print(tabulate(
        table_data,
        headers=[f"{Fore.CYAN}{h}{Style.RESET_ALL}" for h in headers],
        tablefmt="fancy_grid",
        colalign=["center", "center", "center", "center", "left", "left"],
        maxcolwidths=[None, None, None, None, 15, 40]
    ))
    print()  # Add spacing after table


def get_session_selection(sessions: List[SessionFile]) -> SessionFile:
    """Get user's session selection"""
    while True:
        try:
            choice = input(f"\nSelect session (1-{len(sessions)}) or 'q' to quit: ").strip()
            
            if choice.lower() == 'q':
                print("Goodbye!")
                sys.exit(0)
            
            index = int(choice) - 1
            if 0 <= index < len(sessions):
                return sessions[index]
            else:
                print(f"Please enter a number between 1 and {len(sessions)}")
                
        except ValueError:
            print("Please enter a valid number or 'q' to quit")
        except KeyboardInterrupt:
            print("\nGoodbye!")
            sys.exit(0)


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
        # Convert the encoded project name back to the actual file path
        username = os.getenv('USER', 'user')
        user_prefix = f'-Users-{username}-'
        user_path = f'/Users/{username}/'
        actual_project_path = session.project_dir.replace(user_prefix, user_path).replace('-', '/')
        
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
    
    print("Finding Claude Code projects...")
    project_dirs = find_project_directories()
    
    if not project_dirs:
        print("No Claude Code projects with sessions found!")
        print(f"Make sure your projects directory contains .jsonl files: {CLAUDE_PROJECTS_DIR}")
        return
    
    # Step 1: Display and select project directory
    display_project_directories(project_dirs)
    selected_project = get_project_selection(project_dirs)
    
    # Step 2: Find sessions in the selected project
    print(f"\nFinding sessions in {selected_project.name}...")
    sessions = find_session_files_in_project(selected_project)
    
    if not sessions:
        print("No session files found in this project!")
        return
    
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
            print(" (cached) ✓")
        else:
            # Load conversations and generate new summary
            session.load_conversations()
            content = session.extract_content_for_summary()
            session.summary = summarize_with_claude(content)
            # Cache the new summary
            cache_summary(session, session.summary, cache)
            cache_updated = True
            print(" ✓")
    
    # Always save cache after processing
    save_cache_for_project(selected_project, cache)
    
    # Check for and optionally delete empty sessions
    sessions, cache = delete_empty_sessions(sessions, selected_project, cache)
    
    # Save cache again after potential deletions
    save_cache_for_project(selected_project, cache)
    
    if not sessions:
        print("No sessions remaining after cleanup!")
        return
    
    # Step 3: Display sessions and get user selection
    display_name = selected_project.name
    username = os.getenv('USER', 'user')
    user_prefix = f'-Users-{username}-'
    if display_name.startswith(user_prefix):
        display_name = display_name.replace(user_prefix, '').replace('-', '/')
    
    display_sessions(sessions, display_name)
    selected_session = get_session_selection(sessions)
    
    # Launch the selected session
    launch_session(selected_session)


if __name__ == "__main__":
    main()
