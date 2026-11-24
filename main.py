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

            # 4. Read the total comment count shown in the UI sidebar (for logging only)
            total_comment_count = await comment_reader.get_total_comment_count()
            console.print(f"[dim]Instagram shows {total_comment_count} total comment(s) in sidebar.[/dim]")

            # 5. Process comments ONE BY ONE as they appear — scroll only when current batch is exhausted.
            #    This is the natural human pattern: read a comment → visit profile → come back → next comment.
            #    After processing all currently visible comments, we scroll down a bit to reveal the next batch.
            #    Stop signals (checked after each scroll):
            #      ✓ "View hidden comments" text appears   → definitive end-of-list from Instagram
            #      ✓ Spinner visible                       → wait for it, then continue
            #      ✓ 4 scroll rounds with zero new comments → fallback end-of-list
            processed_count = 0        # Profiles actually investigated (non-spam, non-duplicate)
            visited_count = 0          # Every profile opened, regardless of eligibility
            seen_usernames: set = set()  # Track across batches so we never re-process
            scroll_stall_rounds = 0
            MAX_STALL = 4
            reel_done = False

            while not reel_done:
                # Read whatever comments are currently visible in the drawer
                all_visible = await comment_reader.read_accessible_comments(reel_context.reel_id)
                # Only the ones we haven't touched yet this reel
                new_batch = [c for c in all_visible if c.username not in seen_usernames]

                if not new_batch and processed_count == 0:
                    console.print("[dim]No comments found on this Reel. Marking done and advancing to next...[/dim]")
                    state_manager.mark_reel_processed(reel_context.reel_id)
                    await comment_reader.close_comments()
                    if settings.auto_next_reel:
                        await reel_detector.navigate_to_next_reel()
                    reel_done = True
                    break

                # ── Process each unseen comment in the current visible batch ──
                for comment in new_batch:
                    username = comment.username
                    seen_usernames.add(username)

                    if state_manager.is_user_processed(username):
                        console.print(f"[dim]Skipping @{username} (already inspected in session).[/dim]")
                        continue

                    # Fast Spam / Self-Promo Filter
                    is_spam, spam_reason = is_self_promo_or_spam(comment.text)
                    if is_spam:
                        console.print(f"\n[dim yellow]⊘ Skipping @{username}: Self-promo / spam ({spam_reason}): \"{comment.text}\"[/dim yellow]")
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

                    # 5a. Open commenter's profile
                    visited_count += 1
                    clicked = await comment_reader.click_commenter_profile(username)
                    if not clicked:
                        console.print(f"[red]Could not click profile link for @{username}. Marking unavailable.[/red]")
                        profile_data = await profile_inspector.inspect(username)
                    else:
                        await fatigue_model.apply_fatigue_delay(max(settings.min_action_delay, 3.0))
                        await simulate_profile_glance()
                        await browser_controller.wait_for_user_to_resolve_checkpoint()
                        profile_data = await profile_inspector.inspect(username)

                    session_logger.record_profile_opened(
                        has_message_btn=profile_data.message_button_found,
                        is_unavailable=not profile_data.is_accessible
                    )

                    # 5b. Run Decision Engine
                    analysis = await decision_engine.evaluate_commenter(comment, profile_data, reel_context)
                    session_logger.record_analysis(analysis, reel_url=reel_context.url)
                    dashboard.display_prospect_card(analysis)

                    if analysis.decision.value == "ELIGIBLE":
                        console.print(f"\n[bold bright_green]🎯 ELIGIBLE CONVERSATION IDENTIFIED: @{username}![/bold bright_green]")

                        messages_to_send = analysis.message_sequence
                        if not messages_to_send:
                            messages_to_send = [f'"{comment.text}"', analysis.suggested_question or "Hey! Saw your comment on the reel!"]

                        for idx, msg in enumerate(messages_to_send, 1):
                            console.print(f'[bright_green]💬 MESSAGE {idx}: "{msg}"[/bright_green]')

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

                            await asyncio.sleep(0.7)
                            await profile_inspector.close_chat_dialog()
                        else:
                            console.print(f"[yellow]Could not open message dialog for @{username}. Saved to review queue.[/yellow]")

                        console.print("[dim]Saved to review queue: session_data/queue.json (Run 'python ui/cli.py' to view/approve)[/dim]\n")

                    # 5c. Return to reel and reopen comments for next iteration
                    await profile_inspector.return_to_reel_and_reopen_comments(
                        reel_url=reel_context.url,
                        comment_reader=comment_reader
                    )
                    await browser_controller.wait_for_user_to_resolve_checkpoint()

                    processed_count += 1
                    await fatigue_model.apply_fatigue_delay(settings.min_action_delay)
                    await fatigue_model.maybe_take_micro_break()

                # ── Batch done. Now check if there are more comments to load ──

                # Best stop signal: "View hidden comments" = Instagram says we're at the bottom
                if await comment_reader._is_end_of_comments():
                    console.print(f"[dim]✓ 'View hidden comments' marker visible — end of comment list reached.[/dim]")
                    break

                # Spinner: Instagram is mid-load → wait and loop back to read the new batch
                if await comment_reader._is_spinner_visible():
                    console.print(f"[dim]⏳ Spinner detected — waiting for Instagram to load more comments...[/dim]")
                    await comment_reader._wait_for_spinner_to_clear(max_wait=12.0)
                    scroll_stall_rounds = 0
                    continue  # Go back to top of while loop — new comments will be in new_batch

                # No spinner, no end marker → scroll down to trigger next lazy-load batch
                pre_scroll_count = len(await comment_reader.read_accessible_comments(reel_context.reel_id))
                await comment_reader._scroll_comment_drawer(pixels=800)
                await asyncio.sleep(1.3)
                post_scroll_count = len(await comment_reader.read_accessible_comments(reel_context.reel_id))

                if post_scroll_count <= pre_scroll_count:
                    scroll_stall_rounds += 1
                    if scroll_stall_rounds >= MAX_STALL:
                        console.print(f"[dim]✓ No new comments after {MAX_STALL} scroll rounds — end of comment list.[/dim]")
                        break
                else:
                    scroll_stall_rounds = 0  # New comments loaded — keep going

            # 9. All comments for this Reel finished
            console.print(f"\n[green]✓ Completed investigation of all comments on Reel [{reel_context.reel_id}].[/green]")
            console.print(f"[dim]  Profiles visited: {visited_count} | Profiles processed (non-spam/non-dupe): {processed_count} | UI total shown: {total_comment_count}[/dim]")
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

