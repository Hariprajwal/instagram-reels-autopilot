import asyncio
import sys
import time
from typing import Optional

from config.settings import settings
from core.browser_controller import BrowserController
from core.reel_detector import ReelDetector
from core.comment_reader import CommentReader
from core.profile_inspector import ProfileInspector
from core.decision_engine import DecisionEngine
from core.human_simulation import (
    simulate_watching_reel, simulate_reading_comments_pause,
    simulate_profile_glance, human_sleep, micro_pause,
    gauss_delay, fatigue_model
)
from storage.session_logger import SessionLogger
from storage.state_manager import StateManager
from models.classifier import is_self_promo_or_spam
from ui.dashboard import dashboard, console

async def run_agent():
    dashboard.display_banner()
    console.print("[bold yellow]Initializing storage and session managers...[/bold yellow]")

    session_logger = SessionLogger()
    state_manager = StateManager()
    decision_engine = DecisionEngine(session_logger, state_manager)

    browser_controller = BrowserController()
    try:
        page = await browser_controller.connect()
    except Exception as e:
        console.print(f"[bold red]{e}[/bold red]")
        sys.exit(1)

    reel_detector = ReelDetector(page)
    comment_reader = CommentReader(page)
    profile_inspector = ProfileInspector(page)

    console.print("\n[bold green]✓ Agent connected to Chrome![/bold green]")
    console.print("[cyan]The user controls navigation. Please scroll through Instagram Reels.[/cyan]")
    console.print(f"[cyan]When you settle on a Reel for {settings.reel_cooldown_seconds:.0f} seconds, investigation starts automatically.[/cyan]\n")

    # Start the session fatigue model (tracks session age for natural slowdowns)
    fatigue_model.session_start()

    # Periodic 1-Minute Live Metrics Dashboard Heartbeat + Mid-Session Cleanup
    async def periodic_stats_reporter():
        cycle = 0
        while True:
            try:
                await asyncio.sleep(60)
                cycle += 1
                console.print("\n[dim]⏱ [1-Minute Status Heartbeat][/dim]")
                dashboard.display_session_stats(session_logger.stats)
                # Every 5 minutes: clean up old screenshots and trim CSV files
                if cycle % 5 == 0:
                    session_logger.cleanup_old_screenshots(max_age_minutes=15)
                    session_logger._auto_trim_csvs()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    stats_task = asyncio.create_task(periodic_stats_reporter())

    try:
        while True:
            # 1. Wait for user to scroll and settle for cooldown seconds (auto-skips already-processed reels)
            reel_context = await reel_detector.wait_for_user_to_settle_on_reel(state_manager=state_manager)

            console.print(f"\n[bold magenta]════════════════════════════════════════════════════════════[/bold magenta]")
            console.print(f"[bold white]Inspecting Reel:[/bold white] [cyan]{reel_context.reel_id}[/cyan] by @[yellow]{reel_context.author}[/yellow]")
            console.print(f"[dim]URL: {reel_context.url}[/dim]")
            if reel_context.caption:
                console.print(f"[dim]Caption: {reel_context.caption[:120]}...[/dim]")

            session_logger.record_reel_inspected()

            # 2. Simulate watching the Reel before touching comments (inbound ratio balance)
            # This is CRITICAL: Real humans watch content first, then interact.
            await simulate_watching_reel(page)

            # 3. Open Comments Section — wait for page to be fully ready first
            await human_sleep(1.2, 0.3)
            comments_opened = await comment_reader.open_comments()
            if not comments_opened:
                console.print("[yellow]⚠ Could not open comments section for this Reel. Skipping to next...[/yellow]")
                state_manager.mark_reel_processed(reel_context.reel_id)  # Mark to avoid re-trying stuck reel
                await reel_detector.navigate_to_next_reel()
                continue

            # Simulate reading comments before processing (natural delay, Gaussian)
            await simulate_reading_comments_pause()

            # 4. Read accessible comments
            comments = await comment_reader.read_accessible_comments(reel_context.reel_id)
            console.print(f"[cyan]Found {len(comments)} accessible comment(s) on this Reel.[/cyan]")

            if not comments:
                console.print("[dim]No comments found on this Reel. Marking done and advancing to next...[/dim]")
                state_manager.mark_reel_processed(reel_context.reel_id)
                await comment_reader.close_comments()
                if settings.auto_next_reel:
                    await reel_detector.navigate_to_next_reel()
                continue

            # 4. Investigate each commenter individually
            processed_count = 0
            for comment in comments:
                username = comment.username

                if state_manager.is_user_processed(username):
                    console.print(f"[dim]Skipping @{username} (already inspected in session).[/dim]")
                    continue

                # Fast Spam / Self-Promo Filter: Ignore story/profile checks without visiting profile
                is_spam, spam_reason = is_self_promo_or_spam(comment.text)
                if is_spam:
                    console.print(f"\n[dim yellow]⊘ Skipping @{username}: Self-promo / spam detected ({spam_reason}): \"{comment.text}\"[/dim yellow]")
                    state_manager.mark_user_processed(
                        username=username,
                        reel_id=reel_context.reel_id,
                        decision="NOT_INTERESTED",
                        notes=f"Ignored: Self-promo / spam ({spam_reason})"
                    )
                    continue

                session_logger.record_comment_read()
                console.print(f"\n[bold cyan]► Commenter [{processed_count + 1}]:[/bold cyan] @{username}")
                console.print(f'  Comment: [italic]"{comment.text}"[/italic]')

                # Safety checkpoint check
                await browser_controller.wait_for_user_to_resolve_checkpoint()

                # 5. Open commenter's profile (Mandatory Step)
                clicked = await comment_reader.click_commenter_profile(username)
                if not clicked:
                    console.print(f"[red]Could not click profile link for @{username}. Marking unavailable.[/red]")
                    profile_data = await profile_inspector.inspect(username)
                else:
                    # Simulate glancing at profile (natural pause before inspecting)
                    # Fatigue model scales this delay with session age
                    await fatigue_model.apply_fatigue_delay(max(settings.min_action_delay, 3.0))
                    await simulate_profile_glance()
                    # Check if checkpoint appeared on profile load
                    await browser_controller.wait_for_user_to_resolve_checkpoint()
                    profile_data = await profile_inspector.inspect(username)

                session_logger.record_profile_opened(
                    has_message_btn=profile_data.message_button_found,
                    is_unavailable=not profile_data.is_accessible
                )

                # 6. Run Decision Engine (Intent, DM Permission, 1-Question Rule)
                analysis = await decision_engine.evaluate_commenter(comment, profile_data, reel_context)

                # Record analysis in session logger with full Reel URL and Profile link
                session_logger.record_analysis(analysis, reel_url=reel_context.url)

                # 7. Render Prospect Card on Dashboard
                dashboard.display_prospect_card(analysis)

                if analysis.decision.value == "ELIGIBLE":
                    console.print(f"\n[bold bright_green]🎯 ELIGIBLE CONVERSATION IDENTIFIED: @{username}![/bold bright_green]")

                    # Prepare multi-message sequence:
                    # Message 1: The commenter's original comment (quoted for instant context)
                    # Message 2: Personalized reaction & 1-question
                    # Message 3 (Optional): Short friendly follow-up
                    messages_to_send = analysis.message_sequence
                    if not messages_to_send:
                        messages_to_send = [f'"{comment.text}"', analysis.suggested_question or "Hey! Saw your comment on the reel!"]

                    for idx, msg in enumerate(messages_to_send, 1):
                        console.print(f'[bright_green]💬 MESSAGE {idx}: "{msg}"[/bright_green]')

                    # Open Message Dialog in Chrome (floating drawer) and send sequence
                    opened_chat = await profile_inspector.open_message_dialog()
                    if opened_chat:
                        sent = await profile_inspector.send_message_sequence(
                            messages=messages_to_send,
                            auto_send=settings.auto_send_dm
                        )
                        if sent:
                            analysis.message_sent = settings.auto_send_dm
                            if settings.auto_send_dm:
                                session_logger.stats.questions_sent += 1
                                console.print(f"[bold green]✓ All {len(messages_to_send)} message(s) successfully sent to @{username}![/bold green]")
                                session_logger.record_message_sent(
                                    reel_id=reel_context.reel_id,
                                    reel_url=reel_context.url,
                                    username=username,
                                    comment_text=comment.text,
                                    messages=messages_to_send
                                )
                            else:
                                console.print(f"[bold cyan]✓ Messages drafted in Chrome chat box for @{username} (Review & send in Chrome)[/bold cyan]")
                        
                        # Brief pause so the sent message bubble is registered in DOM
                        await asyncio.sleep(0.7)
                        # Close chat drawer before returning to Reel
                        await profile_inspector.close_chat_dialog()
                    else:
                        console.print(f"[yellow]Could not open message dialog for @{username}. Saved to review queue.[/yellow]")

                    console.print("[dim]Saved to review queue: session_data/queue.json (Run 'python ui/cli.py' to view/approve)[/dim]\n")

                # 8. Return to exact original Reel and reopen comments
                await profile_inspector.return_to_reel_and_reopen_comments(
                    reel_url=reel_context.url,
                    comment_reader=comment_reader
                )

                # Check if checkpoint appeared upon returning
                await browser_controller.wait_for_user_to_resolve_checkpoint()

                processed_count += 1
                # Fatigue-scaled inter-commenter delay + occasional micro-break
                await fatigue_model.apply_fatigue_delay(settings.min_action_delay)
                await fatigue_model.maybe_take_micro_break()

                if processed_count >= settings.max_comments_per_reel:
                    console.print(f"[yellow]Reached limit of {settings.max_comments_per_reel} comments for this Reel.[/yellow]")
                    break

            # 9. All comments for this Reel finished
            console.print(f"\n[green]✓ Completed investigation of all comments on Reel [{reel_context.reel_id}].[/green]")
            state_manager.mark_reel_processed(reel_context.reel_id)

            # 10. Close comments drawer and restore original Reel view
            await comment_reader.close_comments()
            await asyncio.sleep(1.0)

            # 11. Display updated Live Statistics
            dashboard.display_session_stats(session_logger.stats)

            # 12. Advance to NEXT Reel via Down Arrow (Automatic condition when all comments finish)
            if settings.auto_next_reel:
                console.print("\n[bold cyan]⚡ All comments finished on this Reel. Automatically advancing to NEXT Reel via Down Arrow...[/bold cyan]")
                await reel_detector.navigate_to_next_reel()
            else:
                console.print("\n[bold cyan]Waiting for you to manually scroll to the next Reel...[/bold cyan]")

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Agent interrupted by operator (Ctrl+C).[/bold yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error in main loop: {e}[/bold red]")
    finally:
        if 'stats_task' in locals() and not stats_task.done():
            stats_task.cancel()

        console.print("\n[bold green]Final Session Summary:[/bold green]")
        dashboard.display_session_stats(session_logger.stats)
        console.print(f"[cyan]• Session report saved to: session_data/session_report.json[/cyan]")
        console.print(f"[cyan]• Leads CSV saved to: session_data/session_leads.csv[/cyan]")
        console.print(f"[cyan]• Messages Sent Log: session_data/messages_sent.csv[/cyan]")
        console.print(f"[cyan]• Lead Review Queue: session_data/queue.json[/cyan]")

        # Clean up temporary screenshots if configured
        if settings.cleanup_screenshots_on_exit:
            session_logger.cleanup_screenshots()

        await browser_controller.close()

if __name__ == "__main__":
    asyncio.run(run_agent())

