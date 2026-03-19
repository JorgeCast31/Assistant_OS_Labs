"""
Chat UI - Interfaz web tipo chat para Assistant OS.
Genera HTML completo con CSS+JS inline, sin dependencias externas.
"""


def generate_chat_html() -> str:
    """
    Genera el HTML completo para la interfaz de chat.
    
    Returns:
        String HTML listo para servir.
    """
    return '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Assistant OS</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        :root {
            --bg-primary: #f5f5f5;
            --bg-secondary: #ffffff;
            --bg-user: #007aff;
            --bg-assistant: #e9e9eb;
            --text-primary: #1c1c1e;
            --text-secondary: #8e8e93;
            --text-user: #ffffff;
            --border-color: #c6c6c8;
            --success-color: #34c759;
            --error-color: #ff3b30;
            --accent-color: #007aff;
            --vh: 1vh;
        }
        
        html {
            height: 100%;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            height: calc(var(--vh, 1vh) * 100);
            min-height: calc(var(--vh, 1vh) * 100);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
        }
        
        @supports (height: 100dvh) {
            body {
                height: 100dvh;
                min-height: 100dvh;
            }
        }
        
        /* Header */
        .header {
            background: var(--bg-secondary);
            padding: 12px 16px;
            padding-top: max(12px, env(safe-area-inset-top));
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
            position: sticky;
            top: 0;
            z-index: 50;
        }
        
        .header-left {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        
        .header-title {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 17px;
            font-weight: 600;
        }
        
        .session-id {
            font-size: 11px;
            color: var(--text-secondary);
            font-family: 'SF Mono', Monaco, monospace;
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--text-secondary);
            transition: background 0.3s;
        }
        
        .status-dot.online { background: var(--success-color); }
        .status-dot.offline { background: var(--error-color); }
        
        .header-actions {
            display: flex;
            gap: 4px;
            flex-wrap: wrap;
            justify-content: flex-end;
        }
        
        .btn-icon {
            background: none;
            border: none;
            color: var(--accent-color);
            font-size: 12px;
            cursor: pointer;
            padding: 5px 8px;
            border-radius: 6px;
            transition: background 0.2s;
            white-space: nowrap;
        }
        
        .btn-icon:hover {
            background: rgba(0, 122, 255, 0.1);
        }
        
        /* Chat area */
        .chat-container {
            flex: 1;
            overflow-y: auto;
            overflow-x: hidden;
            -webkit-overflow-scrolling: touch;
            overscroll-behavior: contain;
            padding: 16px;
            padding-bottom: 80px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        .message {
            max-width: 85%;
            animation: fadeIn 0.2s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .message.user {
            align-self: flex-end;
        }
        
        .message.assistant {
            align-self: flex-start;
        }
        
        .bubble {
            padding: 10px 14px;
            border-radius: 18px;
            line-height: 1.4;
            word-wrap: break-word;
            white-space: pre-wrap;
        }
        
        .message.user .bubble {
            background: var(--bg-user);
            color: var(--text-user);
            border-bottom-right-radius: 4px;
        }
        
        .message.assistant .bubble {
            background: var(--bg-assistant);
            color: var(--text-primary);
            border-bottom-left-radius: 4px;
        }
        
        .message-title {
            font-weight: 600;
            font-size: 13px;
            margin-bottom: 4px;
            color: var(--text-secondary);
        }
        
        .message.assistant .message-title {
            color: var(--accent-color);
        }
        
        .message-actions {
            display: flex;
            gap: 8px;
            margin-top: 8px;
        }
        
        .btn-small {
            background: rgba(0, 0, 0, 0.05);
            border: none;
            color: var(--accent-color);
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 12px;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .btn-small:hover {
            background: rgba(0, 0, 0, 0.1);
        }
        
        .details-panel {
            margin-top: 8px;
            padding: 10px;
            background: rgba(0, 0, 0, 0.03);
            border-radius: 8px;
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 12px;
            overflow-x: auto;
            display: none;
        }
        
        .details-panel.show {
            display: block;
        }
        
        .typing-indicator {
            display: flex;
            gap: 4px;
            padding: 12px 16px;
            align-self: flex-start;
        }
        
        .typing-indicator span {
            width: 8px;
            height: 8px;
            background: var(--text-secondary);
            border-radius: 50%;
            animation: bounce 1.4s infinite ease-in-out;
        }
        
        .typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
        .typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
        
        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }
        
        /* Input area */
        .input-container {
            background: var(--bg-secondary);
            padding: 12px 16px;
            padding-bottom: max(12px, env(safe-area-inset-bottom));
            border-top: 1px solid var(--border-color);
            display: flex;
            gap: 10px;
            align-items: flex-end;
            flex-shrink: 0;
            position: sticky;
            bottom: 0;
            z-index: 40;
        }
        
        .input-wrapper {
            flex: 1;
            background: var(--bg-primary);
            border-radius: 20px;
            padding: 8px 16px;
            border: 1px solid var(--border-color);
        }
        
        #messageInput {
            width: 100%;
            border: none;
            background: transparent;
            font-size: 16px;
            font-family: inherit;
            resize: none;
            outline: none;
            max-height: 120px;
            line-height: 1.4;
        }
        
        .btn-send {
            background: var(--accent-color);
            color: white;
            border: none;
            width: 36px;
            height: 36px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            transition: opacity 0.2s, transform 0.1s;
        }
        
        .btn-send:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .btn-send:active:not(:disabled) {
            transform: scale(0.95);
        }
        
        .btn-send svg {
            width: 18px;
            height: 18px;
        }
        
        /* Token Modal */
        .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
            padding: 20px;
        }
        
        .modal-overlay.hidden {
            display: none;
        }
        
        .modal {
            background: var(--bg-secondary);
            border-radius: 14px;
            padding: 24px;
            width: 100%;
            max-width: 340px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
        }
        
        .modal h2 {
            font-size: 18px;
            margin-bottom: 8px;
        }
        
        .modal p {
            font-size: 14px;
            color: var(--text-secondary);
            margin-bottom: 16px;
        }
        
        .modal input {
            width: 100%;
            padding: 12px;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            font-size: 14px;
            font-family: 'SF Mono', Monaco, monospace;
            margin-bottom: 16px;
        }
        
        .modal-actions {
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        }
        
        .btn-modal {
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            border: none;
        }
        
        .btn-modal.primary {
            background: var(--accent-color);
            color: white;
        }
        
        .btn-modal.secondary {
            background: var(--bg-primary);
            color: var(--text-primary);
        }
        
        /* Empty state */
        .empty-state {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-secondary);
            font-size: 15px;
            text-align: center;
            padding: 40px;
        }
        
        /* Error message */
        .error-bubble {
            background: #ffebee !important;
            border: 1px solid var(--error-color);
        }
        
        .error-bubble .message-title {
            color: var(--error-color) !important;
        }
        
        /* Loading state for history */
        .loading-history {
            text-align: center;
            padding: 20px;
            color: var(--text-secondary);
        }
        
        /* Toast notification */
        .toast {
            position: fixed;
            bottom: 100px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 10px 20px;
            border-radius: 20px;
            font-size: 14px;
            z-index: 200;
            opacity: 0;
            transition: opacity 0.3s;
            pointer-events: none;
        }
        
        .toast.show {
            opacity: 1;
        }
        
        .modal-error {
            color: var(--error-color);
            font-size: 13px;
            margin-bottom: 12px;
            display: none;
        }
        
        .modal-error.show {
            display: block;
        }
        
        /* Intent chip */
        .intent-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(0, 122, 255, 0.1);
            border: 1px solid rgba(0, 122, 255, 0.3);
            border-radius: 12px;
            padding: 4px 10px;
            font-size: 11px;
            color: var(--accent-color);
            margin-top: 6px;
            flex-wrap: wrap;
        }
        
        .intent-chip .chip-domain {
            font-weight: 600;
            background: var(--accent-color);
            color: white;
            padding: 2px 6px;
            border-radius: 6px;
        }
        
        .intent-chip .chip-conf {
            color: var(--text-secondary);
            font-size: 10px;
        }
        
        .intent-chip.overridden {
            border-color: #ff9500;
            background: rgba(255, 149, 0, 0.1);
        }
        
        .intent-chip.overridden .chip-domain {
            background: #ff9500;
        }
        
        /* Mode selector */
        .mode-selector {
            display: flex;
            gap: 4px;
            margin-right: 8px;
        }
        
        .mode-btn {
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
            font-size: 11px;
            padding: 4px 8px;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .mode-btn.active {
            background: var(--accent-color);
            color: white;
            border-color: var(--accent-color);
        }
        
        /* Confirmation panel */
        .confirm-panel {
            background: #fffbea;
            border: 1px solid #f5c518;
            border-radius: 12px;
            padding: 12px;
            margin: 8px 0;
            max-width: 85%;
            align-self: flex-end;
        }
        
        .confirm-panel .confirm-text {
            font-size: 13px;
            color: var(--text-primary);
            margin-bottom: 8px;
        }
        
        .confirm-panel .confirm-actions {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }
        
        .confirm-btn {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            font-size: 12px;
            padding: 6px 12px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .confirm-btn:hover {
            background: var(--bg-primary);
        }
        
        .confirm-btn.primary {
            background: var(--accent-color);
            color: white;
            border-color: var(--accent-color);
        }
        
        /* Domain selector modal */
        .domain-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
            margin-bottom: 16px;
        }
        
        .domain-option {
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px;
            cursor: pointer;
            text-align: center;
            font-size: 13px;
            transition: all 0.2s;
        }
        
        .domain-option:hover {
            border-color: var(--accent-color);
            background: rgba(0, 122, 255, 0.05);
        }
        
        .domain-option .domain-name {
            font-weight: 600;
            margin-bottom: 2px;
        }
        
        .domain-option .domain-desc {
            font-size: 10px;
            color: var(--text-secondary);
        }
        
        /* Warning chip */
        .warning-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: rgba(255, 149, 0, 0.1);
            border: 1px solid rgba(255, 149, 0, 0.3);
            border-radius: 8px;
            padding: 4px 8px;
            font-size: 11px;
            color: #ff9500;
            margin-bottom: 8px;
        }
        
        /* Expense card (FIN domain) */
        .expense-card {
            background: linear-gradient(135deg, #f5f7fa 0%, #e8f4e5 100%);
            border: 1px solid #4caf50;
            border-radius: 12px;
            padding: 16px;
            margin: 8px 0;
            max-width: 90%;
        }
        
        .expense-card .expense-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 12px;
            font-weight: 600;
            color: #2e7d32;
        }
        
        .expense-card .expense-header .amount {
            font-size: 20px;
        }
        
        .expense-card .expense-fields {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 12px;
        }
        
        .expense-card .expense-field {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        
        .expense-card .expense-field label {
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
        }
        
        .expense-card .expense-field input,
        .expense-card .expense-field select {
            padding: 6px 8px;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            font-size: 13px;
            background: white;
        }
        
        .expense-card .expense-field input:focus,
        .expense-card .expense-field select:focus {
            outline: none;
            border-color: var(--accent-color);
        }
        
        .expense-card .expense-field.full-width {
            grid-column: 1 / -1;
        }
        
        .expense-card .expense-actions {
            display: flex;
            gap: 8px;
            justify-content: flex-end;
        }
        
        .expense-card .expense-btn {
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
        }
        
        .expense-card .expense-btn.cancel {
            background: #f5f5f5;
            color: var(--text-primary);
        }
        
        .expense-card .expense-btn.cancel:hover {
            background: #e0e0e0;
        }
        
        .expense-card .expense-btn.confirm {
            background: #4caf50;
            color: white;
        }
        
        .expense-card .expense-btn.confirm:hover {
            background: #43a047;
        }
        
        .expense-card .expense-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .expense-card .expense-warning {
            background: rgba(255, 152, 0, 0.1);
            border: 1px solid rgba(255, 152, 0, 0.3);
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 12px;
            font-size: 12px;
            color: #e65100;
        }
        
        .expense-card .expense-success {
            background: rgba(76, 175, 80, 0.1);
            border: 1px solid rgba(76, 175, 80, 0.3);
            border-radius: 6px;
            padding: 8px;
            font-size: 12px;
            color: #2e7d32;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .expense-card.committed {
            background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
            border-color: #4caf50;
        }
        
        /* Plan card (Plan Always) */
        .plan-card {
            background: linear-gradient(135deg, #e3f2fd 0%, #e8f5e9 100%);
            border-color: #2196f3;
        }
        
        .plan-card .plan-header {
            color: #1565c0;
        }
        
        .plan-card .plan-icon {
            font-size: 18px;
        }
        
        .plan-card .plan-items {
            margin: 12px 0;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        
        .plan-card .plan-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 10px;
            background: rgba(255, 255, 255, 0.7);
            border-radius: 8px;
            font-size: 13px;
        }
        
        .plan-card .plan-item.has-missing {
            border: 1px solid rgba(255, 152, 0, 0.4);
            background: rgba(255, 152, 0, 0.05);
        }
        
        .plan-card .plan-item-num {
            background: #1565c0;
            color: white;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 600;
        }
        
        .plan-card .plan-item-amount {
            font-weight: 600;
            color: #2e7d32;
            min-width: 80px;
        }
        
        .plan-card .plan-item-desc {
            flex: 1;
            color: var(--text-primary);
        }
        
        .plan-card .plan-item-resp {
            font-size: 11px;
            padding: 2px 8px;
            background: rgba(0, 0, 0, 0.05);
            border-radius: 10px;
            color: var(--text-secondary);
        }
        
        .plan-card .plan-item-resp.is-unknown {
            background: rgba(255, 152, 0, 0.15);
            color: #e65100;
        }
        
        /* Plan forms container (multi-expense) */
        .plan-forms-container {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 16px;
        }
        
        .plan-forms-container .expense-card {
            border-color: #2196f3;
        }
        
        .plan-forms-container .expense-card.has-error {
            border-color: var(--error-color);
            background: rgba(255, 59, 48, 0.05);
        }
        
        .plan-action-bar {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 10px;
            padding: 12px 16px;
            background: linear-gradient(135deg, #e3f2fd 0%, #e8f5e9 100%);
            border-radius: 12px;
            border: 1px solid #2196f3;
        }
        
        .plan-action-bar .save-all {
            background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%);
            padding: 10px 20px;
            font-size: 14px;
            font-weight: 600;
        }
        
        .plan-action-bar .save-all-success {
            color: #2e7d32;
            font-weight: 600;
            flex: 1;
        }
        
        .plan-action-bar .save-all-partial {
            color: #e65100;
            font-weight: 500;
            flex: 1;
        }

        /* WORK update card — inline chat form for update confirmations */
        .work-update-card {
            background: linear-gradient(135deg, #f0f4ff 0%, #e8eeff 100%);
            border: 1px solid #5c6bc0;
            border-radius: 12px;
            padding: 16px;
            margin: 4px 0 8px 0;
            max-width: 90%;
            align-self: flex-start;
        }

        .work-update-card .expense-header {
            color: #283593;
        }

        .work-update-card .expense-btn.confirm {
            background: #5c6bc0;
        }

        .work-update-card .expense-btn.confirm:hover {
            background: #3949ab;
        }

        .work-update-card .update-field-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 8px;
            margin-bottom: 12px;
        }

        .work-update-card .update-task-list {
            list-style: none;
            padding: 0;
            margin: 8px 0 12px 0;
            max-height: 180px;
            overflow-y: auto;
            border: 1px solid #c5cae9;
            border-radius: 6px;
            padding: 6px;
        }

        .work-update-card .update-task-list li {
            padding: 4px 2px;
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        /* FIN candidate-amount clarification card */
        .fin-clarify-card {
            background: linear-gradient(135deg, #fff8e1 0%, #fff3cd 100%);
            border: 1px solid #f5c518;
            border-radius: 12px;
            padding: 14px 16px;
            margin: 4px 0 8px 0;
            max-width: 90%;
            align-self: flex-start;
        }

        .fin-clarify-card .clarify-amount {
            font-size: 20px;
            font-weight: 700;
            color: #795548;
            margin-bottom: 10px;
        }

        .fin-clarify-card .clarify-actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        .fin-clarify-card .clarify-btn {
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            border: none;
            transition: background 0.15s;
        }

        .fin-clarify-card .clarify-btn.yes {
            background: #4caf50;
            color: white;
        }

        .fin-clarify-card .clarify-btn.yes:hover { background: #43a047; }

        .fin-clarify-card .clarify-btn.no {
            background: #ff9800;
            color: white;
        }

        .fin-clarify-card .clarify-btn.no:hover { background: #f57c00; }

        .fin-clarify-card .clarify-btn.cancel {
            background: #f5f5f5;
            color: #555;
        }

        .fin-clarify-card .clarify-btn.cancel:hover { background: #e0e0e0; }

        .fin-clarify-card .clarify-btn.otro {
            background: #ff9800;
            color: white;
        }

        .fin-clarify-card .clarify-btn.otro:hover { background: #f57c00; }

        .fin-clarify-card .clarify-btn.apply {
            background: #1976d2;
            color: white;
        }

        .fin-clarify-card .clarify-btn.apply:hover { background: #1565c0; }

        .fin-clarify-card .clarify-other-row {
            display: none;
            align-items: center;
            gap: 8px;
            margin-top: 10px;
        }

        .fin-clarify-card .clarify-other-row.visible { display: flex; }

        .fin-clarify-card .clarify-input {
            width: 90px;
            padding: 6px 10px;
            border: 1.5px solid #f5c518;
            border-radius: 6px;
            font-size: 14px;
            text-align: right;
            outline: none;
        }

        .fin-clarify-card .clarify-input:focus { border-color: #1976d2; }
        .fin-clarify-card .clarify-input.error   { border-color: #d32f2f; }

        .fin-clarify-card .clarify-prompt {
            font-size: 13px;
            color: #555;
            margin-bottom: 10px;
        }
    </style>
</head>
<body>
    <header class="header">
        <div class="header-left">
            <div class="header-title">
                <span class="status-dot" id="statusDot"></span>
                <span>Assistant OS</span>
            </div>
            <div class="session-id" id="sessionId">Session: ...</div>
        </div>
        <div class="header-actions">
            <div class="mode-selector">
                <button class="mode-btn active" data-mode="auto" title="Clasificación automática">Auto</button>
                <button class="mode-btn" data-mode="chat" title="Solo chat, sin ejecutar">Chat</button>
                <button class="mode-btn" data-mode="action" title="Forzar confirmación">Acción</button>
            </div>
            <button class="btn-icon" id="btnCopySession" title="Copy session ID">Copy</button>
            <button class="btn-icon" id="btnJoinSession" title="Join session">Join</button>
            <button class="btn-icon" id="btnNewSession" title="New session">New</button>
            <button class="btn-icon" id="btnReload" title="Reload history">Reload</button>
            <button class="btn-icon" id="btnExport" title="Export chat">Export</button>
            <button class="btn-icon" id="btnClear" title="Clear chat">Clear</button>
            <button class="btn-icon" id="btnToken" title="Clear token">Token</button>
        </div>
    </header>
    
    <div class="chat-container" id="chatContainer">
        <div class="empty-state" id="emptyState">
            Envía un comando para comenzar.<br>
            <small>Ej: CODE: crear módulo math_utils</small>
        </div>
    </div>
    
    <div class="input-container">
        <div class="input-wrapper">
            <textarea id="messageInput" placeholder="Escribe un comando..." rows="1"></textarea>
        </div>
        <button class="btn-send" id="btnSend" disabled>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
            </svg>
        </button>
    </div>
    
    <div class="modal-overlay hidden" id="tokenModal">
        <div class="modal">
            <h2>🔐 Token requerido</h2>
            <p id="tokenModalMessage">Ingresa tu X-Assistant-Token para autenticarte.</p>
            <input type="password" id="tokenInput" placeholder="Token de autenticación">
            <div class="modal-error" id="tokenError"></div>
            <div class="modal-actions">
                <button class="btn-modal primary" id="btnSaveToken">Guardar</button>
            </div>
        </div>
    </div>
        <div class="modal-overlay hidden" id="joinModal">
        <div class="modal">
            <h2>🔗 Join Session</h2>
            <p>Pega el conversation_id de la sesión a la que quieres unirte.</p>
            <input type="text" id="joinInput" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
            <div class="modal-error" id="joinError">ID inválido (mínimo 7 caracteres)</div>
            <div class="modal-actions">
                <button class="btn-modal secondary" id="btnCancelJoin">Cancelar</button>
                <button class="btn-modal primary" id="btnConfirmJoin">Unirse</button>
            </div>
        </div>
    </div>
    
    <div class="modal-overlay hidden" id="domainModal">
        <div class="modal">
            <h2>🎯 Seleccionar dominio</h2>
            <p>Elige el dominio correcto para este mensaje:</p>
            <div class="domain-grid" id="domainGrid">
                <div class="domain-option" data-domain="WORK">
                    <div class="domain-name">WORK</div>
                    <div class="domain-desc">Trabajo institucional</div>
                </div>
                <div class="domain-option" data-domain="PRO_DIAG">
                    <div class="domain-name">PRO_DIAG</div>
                    <div class="domain-desc">Proyecto diagnóstico</div>
                </div>
                <div class="domain-option" data-domain="FIN">
                    <div class="domain-name">FIN</div>
                    <div class="domain-desc">Finanzas personales</div>
                </div>
                <div class="domain-option" data-domain="REL">
                    <div class="domain-name">REL</div>
                    <div class="domain-desc">Relaciones</div>
                </div>
                <div class="domain-option" data-domain="HEALTH">
                    <div class="domain-name">HEALTH</div>
                    <div class="domain-desc">Salud física/mental</div>
                </div>
                <div class="domain-option" data-domain="EIPROTA">
                    <div class="domain-name">EIPROTA</div>
                    <div class="domain-desc">TTI, filosofía, arte</div>
                </div>
                <div class="domain-option" data-domain="ENERGY">
                    <div class="domain-name">ENERGY</div>
                    <div class="domain-desc">Meta-sistema, foco</div>
                </div>
            </div>
            <div class="modal-actions">
                <button class="btn-modal secondary" id="btnCancelDomain">Cancelar</button>
            </div>
        </div>
    </div>
    
    <div class="toast" id="toast">Copied!</div>
        <script>
        // iOS viewport height fix: set --vh to actual viewport height
        function setVH() {
            const vh = window.innerHeight * 0.01;
            document.documentElement.style.setProperty('--vh', vh + 'px');
        }
        setVH();
        window.addEventListener('resize', setVH);
        window.addEventListener('orientationchange', () => {
            setTimeout(setVH, 100);
        });
        
        // Generate UUID v4 (crypto-secure with fallback)
        function generateUUID() {
            if (typeof crypto !== 'undefined' && crypto.randomUUID) {
                return crypto.randomUUID();
            }
            // Fallback for older browsers using crypto.getRandomValues
            if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
                const bytes = new Uint8Array(16);
                crypto.getRandomValues(bytes);
                bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
                bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant RFC4122
                const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
                return hex.slice(0,8) + '-' + hex.slice(8,12) + '-' + hex.slice(12,16) + '-' + hex.slice(16,20) + '-' + hex.slice(20);
            }
            // Last resort fallback (non-secure, for very old browsers)
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        }
        
        // Safe text rendering: handles objects that would render as [object Object]
        function safeText(x) {
            if (x === null || x === undefined) return '';
            if (typeof x === 'string') return x;
            if (typeof x === 'number' || typeof x === 'boolean') return String(x);
            if (typeof x === 'object') {
                // Try common message/error properties first
                if (x.message && typeof x.message === 'string') return x.message;
                if (x.error) {
                    if (typeof x.error === 'string') return x.error;
                    if (typeof x.error === 'object' && x.error.message) return x.error.message;
                }
                // Fallback to JSON
                try {
                    return JSON.stringify(x, null, 2);
                } catch (e) {
                    return '[Error: could not stringify object]';
                }
            }
            return String(x);
        }
        
        // Escape HTML special characters to prevent XSS in innerHTML contexts
        function escapeHtml(text) {
            const str = safeText(text);
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }
        // Format filters for display
        function _formatFilters(filters) {
            if (!filters || typeof filters !== 'object') return '';
            const parts = [];
            if (filters.project) parts.push('proyecto=' + filters.project);
            if (filters.status) {
                const s = Array.isArray(filters.status) ? filters.status.join(',') : filters.status;
                parts.push('status=' + s);
            }
            if (filters.title_keyword) parts.push('keyword=' + filters.title_keyword);
            if (filters.domain) parts.push('domain=' + filters.domain);
            return parts.join(' ');
        }
        
        // State
        const state = {
            token: localStorage.getItem('assistant_token') || '',
            conversationId: localStorage.getItem('assistant_os.conversation_id') || '',
            mode: localStorage.getItem('assistant_os.mode') || 'auto',
            messages: [],
            isLoading: false,
            pendingMessage: null,  // For confirmation flow
            pendingIntent: null,
            // FIN Plan Always state
            finSessionContext: {},
            lastFinPlan: null,
            // Pending Plan for continuity (Pending Resolver)
            pendingPlan: null  // { domain, containerId, planData, createdAt, kind: 'form'|'clarification' }
        };
        
        // Domain descriptions for UI
        const DOMAIN_INFO = {
            'WORK': 'Trabajo institucional',
            'PRO_DIAG': 'Proyecto diagnóstico',
            'FIN': 'Finanzas personales',
            'REL': 'Relaciones',
            'HEALTH': 'Salud física/mental',
            'EIPROTA': 'TTI, filosofía, arte',
            'ENERGY': 'Meta-sistema, foco'
        };
        
        // Initialize conversation_id if not exists
        if (!state.conversationId) {
            state.conversationId = generateUUID();
            localStorage.setItem('assistant_os.conversation_id', state.conversationId);
        }
        
        // Elements
        const chatContainer = document.getElementById('chatContainer');
        const emptyState = document.getElementById('emptyState');
        const messageInput = document.getElementById('messageInput');
        const btnSend = document.getElementById('btnSend');
        const btnClear = document.getElementById('btnClear');
        const btnExport = document.getElementById('btnExport');
        const btnToken = document.getElementById('btnToken');
        const btnNewSession = document.getElementById('btnNewSession');
        const btnReload = document.getElementById('btnReload');
        const btnCopySession = document.getElementById('btnCopySession');
        const btnJoinSession = document.getElementById('btnJoinSession');
        const sessionIdEl = document.getElementById('sessionId');
        const statusDot = document.getElementById('statusDot');
        const tokenModal = document.getElementById('tokenModal');
        const tokenInput = document.getElementById('tokenInput');
        const tokenModalMessage = document.getElementById('tokenModalMessage');
        const tokenError = document.getElementById('tokenError');
        const btnSaveToken = document.getElementById('btnSaveToken');
        const joinModal = document.getElementById('joinModal');
        const joinInput = document.getElementById('joinInput');
        const joinError = document.getElementById('joinError');
        const btnCancelJoin = document.getElementById('btnCancelJoin');
        const btnConfirmJoin = document.getElementById('btnConfirmJoin');
        const toast = document.getElementById('toast');
        const domainModal = document.getElementById('domainModal');
        const domainGrid = document.getElementById('domainGrid');
        const btnCancelDomain = document.getElementById('btnCancelDomain');
        const modeBtns = document.querySelectorAll('.mode-btn');
        
        // Update session ID display
        function updateSessionDisplay() {
            const shortId = state.conversationId.substring(0, 8);
            sessionIdEl.textContent = 'Session: ' + shortId;
        }
        
        // Initialize
        async function init() {
            const tokenPrefix = state.token ? state.token.substring(0, 4) + '...' : 'none';
            console.debug('[Auth] token_present=' + !!state.token + ', token_prefix=' + tokenPrefix);
            updateSessionDisplay();
            checkHealth();
            setInterval(checkHealth, 30000);
            
            if (!state.token) {
                showTokenModal();
            } else {
                // Validate token and load history on startup
                const isValid = await checkAuth();
                if (isValid) {
                    await loadHistory();
                }
            }
            
            updateSendButton();
        }
        
        // Health check
        async function checkHealth() {
            try {
                const res = await fetch('/health');
                const data = await res.json();
                statusDot.className = 'status-dot ' + (data.status === 'ok' ? 'online' : 'offline');
            } catch (e) {
                statusDot.className = 'status-dot offline';
            }
        }
        
        // Token modal
        function showTokenModal(errorMsg = '') {
            tokenError.textContent = errorMsg;
            tokenError.classList.toggle('show', !!errorMsg);
            tokenModal.classList.remove('hidden');
            tokenInput.focus();
        }
        
        function hideTokenModal() {
            tokenModal.classList.add('hidden');
            tokenError.textContent = '';
            tokenError.classList.remove('show');
        }
        
        // Auth check - validates token against backend
        async function checkAuth() {
            const tokenPrefix = state.token ? state.token.substring(0, 4) + '...' : 'none';
            if (!state.token) {
                console.debug('[Auth] status=no_token, token_prefix=' + tokenPrefix);
                showTokenModal();
                return false;
            }
            
            try {
                const res = await fetch('/auth/check', {
                    headers: { 'X-Assistant-Token': state.token }
                });
                
                console.debug('[Auth] status=' + res.status + ', token_prefix=' + tokenPrefix);
                
                if (res.status === 401) {
                    showTokenModal('Token inválido o expirado');
                    return false;
                }
                
                if (!res.ok) {
                    showTokenModal('Error de conexión con el servidor');
                    return false;
                }
                
                return true;
            } catch (e) {
                console.debug('[Auth] status=error, error=' + e.message + ', token_prefix=' + tokenPrefix);
                showTokenModal('No se pudo conectar con el servidor');
                return false;
            }
        }
        
        async function saveToken() {
            const token = tokenInput.value.trim();
            if (token) {
                state.token = token;
                localStorage.setItem('assistant_token', token);
                
                // Validate the token before hiding modal
                const isValid = await checkAuth();
                if (isValid) {
                    hideTokenModal();
                    updateSendButton();
                    tokenInput.value = '';
                    // Load history after token is set
                    await loadHistory();
                }
            }
        }
        
        function clearToken() {
            state.token = '';
            localStorage.removeItem('assistant_token');
            updateSendButton();
            showTokenModal();
        }
        
        // Load chat history from backend
        async function loadHistory() {
            if (!state.token || !state.conversationId) return;
            
            try {
                const url = '/chat/history?conversation_id=' + encodeURIComponent(state.conversationId) + '&limit=50';
                const res = await fetch(url, {
                    headers: { 'X-Assistant-Token': state.token }
                });
                
                if (res.status === 401) {
                    clearToken();
                    return;
                }
                
                const data = await res.json();
                
                if (data.ok && data.items && data.items.length > 0) {
                    // Clear current UI
                    clearChatUI();
                    
                    // Render history items
                    for (const item of data.items) {
                        if (item.role === 'user') {
                            addMessageFromHistory('user', item.text);
                        } else if (item.role === 'assistant') {
                            addMessageFromHistory('assistant', item.summary, {
                                ok: true,
                                title: item.title,
                                details: item.details,
                                context_id: item.context_id
                            });
                        }
                    }
                }
            } catch (e) {
                console.error('Failed to load history:', e);
            }
        }
        
        // Clear chat UI without clearing localStorage
        function clearChatUI() {
            state.messages = [];
            chatContainer.innerHTML = '';
            emptyState.style.display = 'flex';
            chatContainer.appendChild(emptyState);
        }
        
        // Send button state
        function updateSendButton() {
            const hasText = messageInput.value.trim().length > 0;
            const hasToken = state.token.length > 0;
            btnSend.disabled = !hasText || !hasToken || state.isLoading;
        }
        
        // Auto-resize textarea
        function autoResize() {
            messageInput.style.height = 'auto';
            messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
        }
        
        // Add message from history (no animation, no _originalText)
        function addMessageFromHistory(type, content, data = null) {
            emptyState.style.display = 'none';
            
            const msg = document.createElement('div');
            msg.className = 'message ' + type;
            msg.style.animation = 'none'; // No animation for history
            
            const bubble = document.createElement('div');
            bubble.className = 'bubble' + (data && !data.ok ? ' error-bubble' : '');
            
            if (type === 'user') {
                bubble.textContent = safeText(content);
            } else {
                if (data && data.title) {
                    const title = document.createElement('div');
                    title.className = 'message-title';
                    title.textContent = safeText(data.title);
                    bubble.appendChild(title);
                }
                
                const text = document.createElement('div');
                text.textContent = safeText(content);
                bubble.appendChild(text);
                
                // Details button if available
                if (data && data.details) {
                    const actions = document.createElement('div');
                    actions.className = 'message-actions';
                    
                    const detailsPanel = document.createElement('div');
                    detailsPanel.className = 'details-panel';
                    detailsPanel.textContent = JSON.stringify(data.details, null, 2);
                    
                    const btnDetails = document.createElement('button');
                    btnDetails.className = 'btn-small';
                    btnDetails.textContent = 'Detalles';
                    btnDetails.onclick = () => {
                        detailsPanel.classList.toggle('show');
                        btnDetails.textContent = detailsPanel.classList.contains('show') ? 'Ocultar' : 'Detalles';
                    };
                    
                    actions.appendChild(btnDetails);
                    bubble.appendChild(actions);
                    bubble.appendChild(detailsPanel);
                }
            }
            
            msg.appendChild(bubble);
            chatContainer.appendChild(msg);
            
            state.messages.push({ type, content, data, ts: new Date().toISOString() });
        }
        
        // Add message to UI (with animation)
        function addMessage(type, content, data = null) {
            emptyState.style.display = 'none';
            
            const msg = document.createElement('div');
            msg.className = 'message ' + type;
            
            const bubble = document.createElement('div');
            bubble.className = 'bubble' + (data && !data.ok ? ' error-bubble' : '');
            
            if (type === 'user') {
                bubble.textContent = safeText(content);
            } else {
                // Assistant message with title
                if (data && data.title) {
                    const title = document.createElement('div');
                    title.className = 'message-title';
                    title.textContent = safeText(data.title);
                    bubble.appendChild(title);
                }
                
                const text = document.createElement('div');
                text.textContent = safeText(content);
                bubble.appendChild(text);
                
                // Action buttons
                if (data && data.details) {
                    const actions = document.createElement('div');
                    actions.className = 'message-actions';
                    
                    const detailsPanel = document.createElement('div');
                    detailsPanel.className = 'details-panel';
                    detailsPanel.textContent = JSON.stringify(data.details, null, 2);
                    
                    const btnDetails = document.createElement('button');
                    btnDetails.className = 'btn-small';
                    btnDetails.textContent = 'Detalles';
                    btnDetails.onclick = () => {
                        detailsPanel.classList.toggle('show');
                        btnDetails.textContent = detailsPanel.classList.contains('show') ? 'Ocultar' : 'Detalles';
                    };
                    
                    const rawPanel = document.createElement('div');
                    rawPanel.className = 'details-panel';
                    
                    // Only show Raw button if _originalText exists (not for history messages)
                    const hasOriginalText = data._originalText && typeof data._originalText === 'string';
                    
                    const btnRaw = document.createElement('button');
                    btnRaw.className = 'btn-small';
                    btnRaw.textContent = 'Raw';
                    btnRaw.disabled = !hasOriginalText;
                    if (!hasOriginalText) {
                        btnRaw.title = 'No disponible en mensajes del historial';
                    }
                    btnRaw.onclick = async () => {
                        if (!hasOriginalText) return;
                        if (rawPanel.classList.contains('show')) {
                            rawPanel.classList.remove('show');
                            btnRaw.textContent = 'Raw';
                            return;
                        }
                        
                        if (!rawPanel.dataset.loaded) {
                            btnRaw.textContent = '...';
                            try {
                                const res = await fetch('/command/summary?raw=1', {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/json',
                                        'X-Assistant-Token': state.token
                                    },
                                    body: JSON.stringify({ 
                                        text: data._originalText,
                                        conversation_id: state.conversationId
                                    })
                                });
                                const raw = await res.json();
                                rawPanel.textContent = JSON.stringify(raw.raw, null, 2);
                                rawPanel.dataset.loaded = 'true';
                            } catch (e) {
                                rawPanel.textContent = 'Error loading raw: ' + e.message;
                            }
                        }
                        
                        rawPanel.classList.add('show');
                        btnRaw.textContent = 'Ocultar Raw';
                    };
                    
                    actions.appendChild(btnDetails);
                    actions.appendChild(btnRaw);
                    bubble.appendChild(actions);
                    bubble.appendChild(detailsPanel);
                    bubble.appendChild(rawPanel);
                }
                
                // Add intent chip for assistant messages with intent
                if (data && data.intent) {
                    // Enrich intent with filters and route info from response
                    const enrichedIntent = { ...data.intent };
                    if (data._filters) {
                        enrichedIntent.filters = data._filters;
                    }
                    if (data.route && !enrichedIntent.operation) {
                        enrichedIntent.operation = data.route;
                    }
                    const chip = createIntentChip(enrichedIntent, data.intent_overridden || false);
                    bubble.appendChild(chip);
                }
                
                // Show route badge if no intent but route is present
                if (data && data.route && !data.intent) {
                    const routeBadge = document.createElement('div');
                    routeBadge.className = 'intent-chip';
                    routeBadge.innerHTML = '<span class="chip-domain">' + escapeHtml(data.route) + '</span>';
                    if (data._filters) {
                        const filterText = _formatFilters(data._filters);
                        if (filterText) {
                            const filterSpan = document.createElement('span');
                            filterSpan.style.color = '#34c759';
                            filterSpan.style.fontSize = '10px';
                            filterSpan.textContent = filterText;
                            routeBadge.appendChild(filterSpan);
                        }
                    }
                    bubble.appendChild(routeBadge);
                }
            }
            
            msg.appendChild(bubble);
            chatContainer.appendChild(msg);
            scrollToBottom();
            
            state.messages.push({ 
                id: generateUUID(),
                type, 
                content, 
                data,
                intent: data ? data.intent : null,
                intent_overridden: data ? (data.intent_overridden || false) : false,
                ts: new Date().toISOString() 
            });
        }
        
        // Typing indicator
        function showTyping() {
            const typing = document.createElement('div');
            typing.id = 'typingIndicator';
            typing.className = 'typing-indicator';
            typing.innerHTML = '<span></span><span></span><span></span>';
            chatContainer.appendChild(typing);
            scrollToBottom();
        }
        
        function hideTyping() {
            const typing = document.getElementById('typingIndicator');
            if (typing) typing.remove();
        }
        
        function scrollToBottom() {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        
        // ---------------------------------------------------------------------------
        // Pending Resolver: Heuristic follow-up parser
        // ---------------------------------------------------------------------------
        
        /**
         * Parse user message as follow-up when there's a pending plan.
         * Returns: { action: 'CANCEL'|'CONFIRM'|'EDIT_SPLIT'|'ESCAPE'|'CLARIFY_AMOUNT'|'UNKNOWN', data: any }
         */
        function parseFollowUp(text) {
            const lower = text.toLowerCase().trim();
            
            // CANCEL patterns - removed "no/nope" since they are ambiguous ("no, era $15")
            if (/^(cancelar|cancela|olvida|borra todo|descartar|olv[ií]dalo)$/i.test(lower)) {
                return { action: 'CANCEL', data: null };
            }
            
            // CONFIRM patterns
            if (/^(confirmar|confirmo|ok|s[ií]|si|yes|dale|guardar|listo|confirma|vale|correcto|adelante|claro|bueno|exacto|exact[ao])$/i.test(lower)) {
                return { action: 'CONFIRM', data: null };
            }
            
            // ESCAPE patterns (explicit topic change)
            if (/^(cambiar de tema|nuevo tema|olvida eso|otra cosa|cambio de tema)/i.test(lower)) {
                return { action: 'ESCAPE', data: null };
            }
            
            // EDIT_SPLIT patterns: "separa X y Y", "X y Y separados", "ana y conejos separados"
            const splitMatch = lower.match(/sep[aá]ra?r?\s+(.+?)\s+y\s+(.+)/i) ||
                               lower.match(/(.+?)\s+y\s+(.+?)\s+sep[aá]rad[oa]s?/i);
            if (splitMatch) {
                return { action: 'EDIT_SPLIT', data: { entity1: splitMatch[1].trim(), entity2: splitMatch[2].trim() } };
            }
            
            // Bare integer/decimal — treat as a monetary amount clarification.
            // Must be the ENTIRE message (possibly with whitespace) with no other words,
            // so that single-word commands like "ok" are not affected.
            const bareNumMatch = /^\\s*(\\d+(?:[.,]\\d{1,2})?)\\s*$/.exec(text);
            if (bareNumMatch) {
                const amount = parseFloat(bareNumMatch[1].replace(',', '.'));
                if (amount > 0) {
                    return { action: 'CLARIFY_AMOUNT', data: { amounts: [amount], originalText: text } };
                }
            }

            // CLARIFY_AMOUNT patterns: "era $15", "fueron $30", "eran 15$", "mcdonalds 15$", "$X" anywhere
            // Detect if the message contains monetary amounts (clarification response)
            const hasMoneyPattern = /\$\s*\d+|\d+\s*\$|b\/\.?\s*\d+|\d+\s*d[oó]lare?s?/i.test(text);
            const clarifyPattern = /^(era|eran|fueron?|fue|el monto (fue|era)|mejor|no[\s,]+|s[ií][\s,]+)/i.test(lower);

            if (hasMoneyPattern || clarifyPattern) {
                // Extract amounts from the clarification
                const amounts = [];
                const patterns = [
                    /\$\s*(\d+(?:[.,]\d{1,2})?)/g,
                    /(\d+(?:[.,]\d{1,2})?)\s*\$/g,
                    /b\/\.?\s*(\d+(?:[.,]\d{1,2})?)/gi,
                    /(\d+(?:[.,]\d{1,2})?)\s*d[oó]lare?s?/gi
                ];

                for (const pat of patterns) {
                    let m;
                    while ((m = pat.exec(text)) !== null) {
                        amounts.push(parseFloat(m[1].replace(',', '.')));
                    }
                }

                // Bare-number fallback: "eran 30", "mejor 30" have no symbol but clarifyPattern matched.
                if (amounts.length === 0 && clarifyPattern) {
                    const bareNum = /\b(\d+(?:[.,]\d{1,2})?)\b/.exec(text);
                    if (bareNum) {
                        amounts.push(parseFloat(bareNum[1].replace(',', '.')));
                    }
                }

                if (amounts.length > 0) {
                    return { action: 'CLARIFY_AMOUNT', data: { amounts, originalText: text } };
                }
            }
            
            // UNKNOWN - could still be a clarification or edit
            return { action: 'UNKNOWN', data: { text: text } };
        }
        
        /**
         * Handle follow-up when a candidate-amount clarification card is visible.
         * Returns true if handled.
         */
        async function handleCandidateClarification(text, followUp, pending) {
            const { candidateAmount } = pending;
            // Authoritative source: pending.originalText (always set by renderCandidateAmountCard
            // from the live `text` parameter of handleFinPlan).
            // Secondary fallback: state.finSessionContext is updated by handleFinPlan immediately
            // before renderCandidateAmountCard is called, so it always has the latest original_text.
            const originalText = pending.originalText
                || (state.finSessionContext
                    && state.finSessionContext.pending_clarification
                    && state.finSessionContext.pending_clarification.original_text)
                || '';
            const card = pending.containerId ? document.getElementById(pending.containerId) : null;

            const removeCard = () => {
                if (card) card.remove();
                state.pendingPlan = null;
            };

            // Bare number: treat as a corrected/confirmed amount
            const bareNum = /^\\s*(\\d+(?:[.,]\\d{1,2})?)\\s*$/.exec(text);
            if (bareNum) {
                const confirmedAmount = parseFloat(bareNum[1].replace(',', '.'));
                addMessage('user', text, { intent: { domain: 'FIN', action: 'clarify_amount' } });
                removeCard();
                const injected = _injectCandidateAmount(originalText, confirmedAmount, candidateAmount);
                await handleFinPlan(injected, { domain: 'FIN' }, null, { skip_candidate_clarification: true });
                return true;
            }

            switch (followUp.action) {
                case 'CONFIRM':
                    // User confirmed the candidate amount (e.g. "sí", "ok", "vale")
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'confirm_candidate' } });
                    removeCard();
                    await handleFinPlan(
                        _injectCandidateAmount(originalText, candidateAmount, candidateAmount),
                        { domain: 'FIN' }, null, { skip_candidate_clarification: true }
                    );
                    return true;

                case 'CLARIFY_AMOUNT': {
                    // User provided a corrected amount (e.g. "era $30")
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'clarify_amount' } });
                    removeCard();
                    const corrected = followUp.data.amounts[0];
                    const correctedText = _injectCandidateAmount(originalText, corrected, candidateAmount);
                    await handleFinPlan(correctedText, { domain: 'FIN' }, null, { skip_candidate_clarification: true });
                    return true;
                }

                case 'CANCEL':
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'cancel_pending' } });
                    removeCard();
                    state.lastFinPlan = null;
                    addMessage('assistant', 'Cancelado.', { ok: true, title: 'FIN · cancelado' });
                    return true;

                case 'ESCAPE':
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'escape_pending' } });
                    removeCard();
                    state.lastFinPlan = null;
                    addMessage('assistant', 'Plan descartado. Puedes continuar con otro tema.', { ok: true, title: 'FIN · escape' });
                    return false;  // Allow normal classify to proceed

                case 'UNKNOWN':
                default: {
                    const lower = text.toLowerCase().trim();
                    // "no" / "corregir" → switch to text clarification
                    if (/^(no|nope|corregir|cambiar|otro)$/i.test(lower)) {
                        addMessage('user', text, { intent: { domain: 'FIN', action: 'clarify_amount' } });
                        if (card) card.remove();
                        state.pendingPlan = {
                            domain: 'FIN',
                            containerId: null,
                            planData: planData,
                            createdAt: Date.now(),
                            kind: 'clarification',
                        };
                        addMessage('assistant', 'Indica el monto correcto (ej: "$15" o "era $30").', { ok: true, title: 'FIN · clarificar' });
                        return true;
                    }
                    // Unknown follow-up — remind user
                    addMessage('user', text, { intent: null });
                    addMessage('assistant',
                        'Vi un posible monto: $' + Math.round(candidateAmount) + '. Responde:\\n• "Sí" para confirmarlo\\n• Un monto correcto, ej: "$30"\\n• "No" para escribir manualmente\\n• "Cancelar" para descartar',
                        { ok: true, title: 'FIN · clarificar' });
                    return true;
                }
            }
        }

        /**
         * Handle follow-up for pending plan.
         * Returns true if handled, false if should proceed to normal classify.
         */
        async function handlePendingFollowUp(text, followUp) {
            const pending = state.pendingPlan;

            // ---- DOM-backed routing guard ----------------------------------------
            // A .fin-clarify-card in the DOM is the source of truth for an active
            // candidate-amount clarification, regardless of what state.pendingPlan
            // currently says.  This handles the case where state.pendingPlan.kind
            // gets overwritten by a previous form or clarification flow while the
            // candidate card is still visible.
            const activeCard = document.querySelector('.fin-clarify-card');
            if (activeCard) {
                const cardCandidateAmount = parseFloat(activeCard.dataset.candidateAmount || '0');
                if (cardCandidateAmount) {
                    // Prefer state.pendingPlan.originalText (set from the live `text` parameter
                    // at card creation time) over dataset.originalText (DOM attribute, can be
                    // absent after DOM manipulation).
                    const cardOriginalText = (pending && pending.originalText)
                        || activeCard.dataset.originalText
                        || '';
                    const cardPending = {
                        kind: 'candidate_clarification',
                        candidateAmount: cardCandidateAmount,
                        originalText: cardOriginalText,
                        containerId: activeCard.id,
                        planData: (pending && pending.planData) || null,
                    };
                    // Re-sync state.pendingPlan so later checks are also correct
                    state.pendingPlan = cardPending;
                    console.log('[PendingResolver] Restored candidate_clarification from DOM card');
                    return await handleCandidateClarification(text, followUp, cardPending);
                }
            }
            // -----------------------------------------------------------------------

            if (!pending) return false;

            // Candidate-amount clarification card is active — route to its handler
            if (pending.kind === 'candidate_clarification') {
                return await handleCandidateClarification(text, followUp, pending);
            }

            // Missing-amount clarification: user may type a bare number as free-text fallback.
            // The structured card is the primary UI path, but intercept here too so context
            // is never lost if the user types the amount as plain text.
            if (pending.kind === 'missing_amount_clarification') {
                const bareNum = /^\s*(\d+(?:[.,]\d{1,2})?)\s*$/.exec(text);
                if (bareNum) {
                    const entered = parseFloat(bareNum[1].replace(',', '.'));
                    if (entered > 0) {
                        const missingCard = document.querySelector('.fin-clarify-card');
                        if (missingCard) missingCard.remove();
                        state.pendingPlan = null;
                        addMessage('user', 'Monto: $' + entered.toFixed(2).replace('.00', ''), { intent: { domain: 'FIN', action: 'clarify_amount' } });
                        const injected = _injectCandidateAmount(pending.originalText, entered, null);
                        await handleFinPlan(injected, { domain: 'FIN' }, null, { skip_candidate_clarification: true });
                        return true;
                    }
                }
                if (followUp.action === 'CANCEL' || followUp.action === 'ESCAPE') {
                    const missingCard = document.querySelector('.fin-clarify-card');
                    if (missingCard) missingCard.remove();
                    state.pendingPlan = null;
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'cancel_pending' } });
                    addMessage('assistant', 'Entendido, cancelado.', { ok: true, title: 'FIN · cancelado' });
                    return true;
                }
                // Non-numeric, non-cancel: remind user to use the input card
                addMessage('user', text, { intent: null });
                addMessage('assistant', 'Por favor indica el monto del gasto en el campo de arriba (ej: 25 o 12.50).', { ok: true, title: 'FIN · clarificar' });
                return true;
            }

            const container = document.getElementById(pending.containerId);

            switch (followUp.action) {
                case 'CANCEL':
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'cancel_pending' } });
                    if (container) {
                        container.remove();
                    }
                    state.pendingPlan = null;
                    state.lastFinPlan = null;
                    addMessage('assistant', 'Plan cancelado.', { ok: true, title: 'FIN · cancelado' });
                    return true;
                
                case 'CONFIRM':
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'confirm_pending' } });
                    if (container) {
                        await window.saveAllExpenses(pending.containerId);
                    }
                    state.pendingPlan = null;
                    return true;
                
                case 'ESCAPE':
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'escape_pending' } });
                    if (container) {
                        container.remove();
                    }
                    state.pendingPlan = null;
                    state.lastFinPlan = null;
                    addMessage('assistant', 'Plan anterior descartado. Puedes continuar con otro tema.', { ok: true, title: 'FIN · escape' });
                    return false;  // Allow normal classify to proceed
                
                case 'EDIT_SPLIT':
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'edit_pending' } });
                    // Try to apply split edit to pending plan
                    const splitApplied = applyEditSplit(pending, followUp.data);
                    if (splitApplied) {
                        addMessage('assistant', splitApplied.message, { ok: true, title: 'FIN · editado' });
                    } else {
                        addMessage('assistant', 'No pude aplicar esa edición automáticamente. Por favor edita los campos directamente en los formularios arriba.', { ok: false, title: 'FIN · aclarar' });
                    }
                    return true;
                
                case 'CLARIFY_AMOUNT':
                    addMessage('user', text, { intent: { domain: 'FIN', action: 'clarify_amount' } });
                    // The user is providing clarification with amounts
                    // Combine original text with clarification and re-plan
                    if (container) {
                        container.remove();
                    }
                    state.pendingPlan = null;
                    
                    // Re-call /fin/plan with the clarification text
                    // The clarification should contain the actual amounts now
                    await handleFinPlan(text, { domain: 'FIN', action: 'clarify' });
                    return true;
                
                case 'UNKNOWN':
                default:
                    // Check if the message might be a continuation for FIN
                    // If it looks like FIN-related, re-process it
                    const looksLikeFin = /gasto|compra|pag[oué]|compr[eé]|gast[eé]|\$|b\/\./i.test(text);
                    if (looksLikeFin) {
                        addMessage('user', text, { intent: { domain: 'FIN', action: 'continue' } });
                        if (container) {
                            container.remove();
                        }
                        state.pendingPlan = null;
                        await handleFinPlan(text, { domain: 'FIN', action: 'continue' });
                        return true;
                    }
                    
                    // Show reminder that there's a pending plan
                    addMessage('user', text, { intent: null });
                    addMessage('assistant', 'Aún tienes un plan FIN pendiente arriba. Puedes:\\n• Editar los campos y presionar "Confirmar"\\n• Escribir "cancelar" para descartar\\n• Escribir "cambiar de tema" para continuar con otra cosa\\n• O indica los montos con $ (ej: "era $15")', { ok: true, title: 'FIN · pendiente' });
                    return true;
            }
        }
        
        /**
         * Try to apply EDIT_SPLIT to pending plan items.
         * Very simple heuristic: look for entity names in descriptions/responsables.
         */
        function applyEditSplit(pending, data) {
            const container = document.getElementById(pending.containerId);
            if (!container) return null;
            
            const cards = container.querySelectorAll('.expense-card:not(.committed)');
            if (cards.length < 2) return null;
            
            const { entity1, entity2 } = data;
            const e1Lower = entity1.toLowerCase();
            const e2Lower = entity2.toLowerCase();
            
            // Check if entities match known responsables
            const responsables = ['ana', 'conejos', 'jorge', 'eiprota', 'proyectos', 'hogar'];
            const e1IsResp = responsables.includes(e1Lower);
            const e2IsResp = responsables.includes(e2Lower);
            
            let changes = [];
            
            // Simple assignment: if both are responsables, assign to first two items
            if (e1IsResp && e2IsResp && cards.length >= 2) {
                const card1 = cards[0];
                const card2 = cards[1];
                
                const select1 = card1.querySelector('.expResponsable');
                const select2 = card2.querySelector('.expResponsable');
                
                if (select1 && select2) {
                    // Capitalize
                    const resp1 = entity1.charAt(0).toUpperCase() + entity1.slice(1).toLowerCase();
                    const resp2 = entity2.charAt(0).toUpperCase() + entity2.slice(1).toLowerCase();
                    
                    select1.value = resp1;
                    select2.value = resp2;
                    
                    changes.push('Item 1 → ' + resp1);
                    changes.push('Item 2 → ' + resp2);
                }
            }
            
            if (changes.length > 0) {
                return { applied: true, message: 'Responsables actualizados: ' + changes.join(', ') + '. Revisa y confirma.' };
            }
            
            return null;
        }
        
        // Send message
        async function sendMessage() {
            const text = messageInput.value.trim();
            if (!text || !state.token || state.isLoading) return;
            
            state.isLoading = true;
            updateSendButton();
            
            messageInput.value = '';
            autoResize();
            
            // ---------------------------------------------------------------------------
            // PENDING RESOLVER: Check for pending plan BEFORE re-classifying
            // ---------------------------------------------------------------------------
            // Safety net: if state.pendingPlan is null but a candidate-amount card is
            // still visible in the DOM (e.g. because state was reset by another flow),
            // rebuild the pending state from the card's data attributes so routing works.
            if (!state.pendingPlan) {
                const orphanCard = document.querySelector('.fin-clarify-card');
                if (orphanCard) {
                    const orphanAmount = parseFloat(orphanCard.dataset.candidateAmount || '0');
                    if (orphanAmount) {
                        console.log('[PendingResolver] Rebuilding candidate_clarification from orphan card');
                        state.pendingPlan = {
                            kind: 'candidate_clarification',
                            candidateAmount: orphanAmount,
                            originalText: orphanCard.dataset.originalText || '',
                            containerId: orphanCard.id,
                            planData: null,
                        };
                    }
                }
            }

            if (state.pendingPlan) {
                const followUp = parseFollowUp(text);
                console.log('[PendingResolver] Detected pending plan, parsed follow-up:', followUp);
                
                const handled = await handlePendingFollowUp(text, followUp);
                if (handled) {
                    state.isLoading = false;
                    updateSendButton();
                    return;
                }
                // If ESCAPE action returned false, continue to normal classify
            }
            
            // Mode: Chat - never execute, just log
            if (state.mode === 'chat') {
                const msgEl = addMessage('user', text, { intent: null, intent_overridden: false });
                addMessage('assistant', 'OK (chat-only) - Mensaje registrado sin ejecutar.', { 
                    ok: true, 
                    title: 'CHAT · registro',
                    intent: null
                });
                state.isLoading = false;
                updateSendButton();
                return;
            }
            
            // Step 1: Classify the message
            let intent = null;
            let classifyFailed = false;
            
            try {
                const classifyRes = await fetch('/classify', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify({
                        text: text,
                        mode: state.mode,
                        conversation_id: state.conversationId
                    })
                });
                
                if (classifyRes.ok) {
                    const classifyData = await classifyRes.json();
                    if (classifyData.ok && classifyData.intent) {
                        intent = classifyData.intent;
                    }
                }
            } catch (e) {
                console.warn('Classification failed:', e);
                classifyFailed = true;
            }
            
            // Add user message with intent chip
            const userMsgEl = addMessageWithIntent('user', text, intent, false);
            
            // Show warning if classifier unavailable
            if (classifyFailed) {
                showWarningChip(userMsgEl, 'Clasificador no disponible');
            }
            
            // ================================================================
            // ROUTING: Operation-based routing has PRIORITY over domain
            // WORK_CREATE and WORK_DELETE have their own ConfirmCard flow
            // ================================================================
            const operation = intent ? intent.operation : null;
            const domain = intent ? intent.domain : null;
            
            // Generate msg_id for tracing this request through the pipeline
            const msgId = 'msg_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 4);
            
            // [INSTRUMENTATION] Router decision
            console.log('[Router] msg_id=' + msgId + ', intent.operation=' + (operation || 'null') + ', domain=' + (domain || 'null'));
            
            // Priority 1: WORK_QUERY operation -> /work/query (no confirmation needed)
            if (operation === 'WORK_QUERY') {
                console.log('[Router] msg_id=' + msgId + ', endpoint=/work/query');
                await executeWorkQuery(text, intent, false, msgId);
                state.isLoading = false;
                updateSendButton();
                return;
            }
            
            // Priority 2: WORK_CREATE, WORK_DELETE, or WORK_UPDATE -> /command/summary
            if (operation === 'WORK_CREATE' || operation === 'WORK_DELETE' || operation === 'WORK_UPDATE') {
                console.log('[Router] msg_id=' + msgId + ', endpoint=/command/summary (mutation: ' + operation + ')');
                await executeWorkMutation(text, intent, false, msgId);
                state.isLoading = false;
                updateSendButton();
                return;
            }
            
            // For other operations: check if old confirmation panel is needed
            const needsConfirm = intent && (
                intent.needs_confirmation || 
                (state.mode === 'action' && intent.confidence < 0.90)
            );
            
            if (needsConfirm && !classifyFailed && operation !== 'FIN_EXPENSE') {
                // Show confirmation panel (for non-WORK, non-FIN mutations)
                state.pendingMessage = text;
                state.pendingIntent = intent;
                showConfirmationPanel(intent);
                state.isLoading = false;
                updateSendButton();
                return;
            }
            
            // Priority 3: FIN_EXPENSE operation OR FIN domain -> /fin/plan
            if (operation === 'FIN_EXPENSE' || domain === 'FIN') {
                console.log('[Router] msg_id=' + msgId + ', endpoint=/fin/plan');
                await handleFinPlan(text, intent, msgId);
                state.isLoading = false;
                updateSendButton();
                return;
            }
            
            // Default: execute via command pipeline
            console.log('[Router] msg_id=' + msgId + ', endpoint=/command (default CODE/DOC)');
            await executeCommand(text, intent, false, msgId);
        }
        
        // Handle FIN Plan Always: call /fin/plan and show plan card
        // Render a button-based clarification card when there is a single clear
        // numeric candidate (no currency symbol) in the user's FIN message.
        function renderCandidateAmountCard(candidateAmount, planData, originalText) {
            const amtLabel = '$' + Math.round(candidateAmount);
            const cardId = 'clarify-card-' + Date.now().toString(36);

            const card = document.createElement('div');
            card.className = 'fin-clarify-card';
            card.id = cardId;
            // Store key data on the element so routing can recover even if
            // state.pendingPlan.kind gets overwritten by another flow.
            card.dataset.candidateAmount = String(candidateAmount);
            card.dataset.originalText = originalText;

            const amtDiv = document.createElement('div');
            amtDiv.className = 'clarify-amount';
            amtDiv.textContent = amtLabel;
            card.appendChild(amtDiv);

            const actions = document.createElement('div');
            actions.className = 'clarify-actions';

            // "Sí, usar $N" — inject $ before the bare number in the original text
            // so fin/plan can parse it as a proper monetary amount.
            const btnYes = document.createElement('button');
            btnYes.className = 'clarify-btn yes';
            btnYes.textContent = 'Sí, usar ' + amtLabel;
            btnYes.onclick = () => {
                card.remove();
                state.pendingPlan = null;
                handleFinPlan(
                    _injectCandidateAmount(originalText, candidateAmount, candidateAmount),
                    { domain: 'FIN' }, null, { skip_candidate_clarification: true }
                );
            };

            // "Otro monto" — reveals an inline numeric input (structured correction).
            // This replaces the old free-text "No, corregir monto" path, which was
            // fragile because it could lose semantic context on re-classification.
            const btnOtro = document.createElement('button');
            btnOtro.className = 'clarify-btn otro';
            btnOtro.textContent = 'Otro monto';
            btnOtro.onclick = () => {
                otroRow.classList.toggle('visible');
                if (otroRow.classList.contains('visible')) {
                    inputOtro.focus();
                    inputOtro.select();
                }
            };

            // "Cancelar"
            const btnCancel = document.createElement('button');
            btnCancel.className = 'clarify-btn cancel';
            btnCancel.textContent = 'Cancelar';
            btnCancel.onclick = () => {
                card.remove();
                state.pendingPlan = null;
            };

            actions.appendChild(btnYes);
            actions.appendChild(btnOtro);
            actions.appendChild(btnCancel);
            card.appendChild(actions);

            // Inline "Otro monto" input row (hidden until btnOtro is clicked).
            // Submitting here goes directly through _injectCandidateAmount so the
            // original message context is always preserved.
            const otroRow = document.createElement('div');
            otroRow.className = 'clarify-other-row';

            const inputOtro = document.createElement('input');
            inputOtro.type = 'number';
            inputOtro.min = '0.01';
            inputOtro.step = '0.01';
            inputOtro.placeholder = '0.00';
            inputOtro.className = 'clarify-input';

            const btnApply = document.createElement('button');
            btnApply.className = 'clarify-btn apply';
            btnApply.textContent = 'Aplicar monto';

            const applyCorrection = () => {
                const raw = inputOtro.value.trim().replace(',', '.');
                const entered = parseFloat(raw);
                if (!entered || entered <= 0 || isNaN(entered)) {
                    inputOtro.classList.add('error');
                    inputOtro.focus();
                    return;
                }
                inputOtro.classList.remove('error');
                const userLabel = '$' + entered.toFixed(2).replace('.00', '');
                addMessage('user', 'Otro monto: ' + userLabel, { intent: { domain: 'FIN', action: 'clarify_amount' } });
                card.remove();
                state.pendingPlan = null;
                const injected = _injectCandidateAmount(originalText, entered, candidateAmount);
                handleFinPlan(injected, { domain: 'FIN' }, null, { skip_candidate_clarification: true });
            };

            btnApply.onclick = applyCorrection;
            // Enter key in the input also submits
            inputOtro.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); applyCorrection(); }
            });

            otroRow.appendChild(inputOtro);
            otroRow.appendChild(btnApply);
            card.appendChild(otroRow);

            chatContainer.appendChild(card);
            scrollToBottom();

            // Set pendingPlan so free-text follow-ups are intercepted by the resolver
            state.pendingPlan = {
                domain: 'FIN',
                containerId: cardId,
                planData: planData,
                createdAt: Date.now(),
                kind: 'candidate_clarification',
                candidateAmount: candidateAmount,
                originalText: originalText,
            };
        }

        /**
         * Render a structured inline input card when NO amount was detected at all.
         *
         * Unlike renderCandidateAmountCard (which has a suggested amount to confirm or
         * correct), this card shows the input immediately — there is no candidate to
         * accept or reject.  On submit it injects the entered amount into the ORIGINAL
         * user message via _injectCandidateAmount (tier-3 prepend) and calls
         * handleFinPlan with skip_candidate_clarification=true so the backend goes
         * directly to plan generation without re-opening the candidate loop.
         */
        function renderMissingAmountCard(originalText, clarificationPrompt, intent) {
            const cardId = 'missing-amt-card-' + Date.now().toString(36);

            const card = document.createElement('div');
            card.className = 'fin-clarify-card';
            card.id = cardId;
            // No data-candidate-amount so the DOM guard in handlePendingFollowUp
            // does not confuse this with an active candidate-clarification card.
            card.dataset.originalText = originalText;

            // Prompt label
            const promptDiv = document.createElement('div');
            promptDiv.className = 'clarify-prompt';
            promptDiv.textContent = clarificationPrompt || '¿Cuál es el monto del gasto?';
            card.appendChild(promptDiv);

            // Input row — always visible (no toggle button needed)
            const inputRow = document.createElement('div');
            inputRow.className = 'clarify-other-row visible';

            const inputAmt = document.createElement('input');
            inputAmt.type = 'number';
            inputAmt.min = '0.01';
            inputAmt.step = '0.01';
            inputAmt.placeholder = '0.00';
            inputAmt.className = 'clarify-input';

            const btnApply = document.createElement('button');
            btnApply.className = 'clarify-btn apply';
            btnApply.textContent = 'Aplicar monto';

            const btnCancel = document.createElement('button');
            btnCancel.className = 'clarify-btn cancel';
            btnCancel.textContent = 'Cancelar';
            btnCancel.onclick = () => {
                card.remove();
                state.pendingPlan = null;
            };

            const applyAmount = () => {
                const raw = inputAmt.value.trim().replace(',', '.');
                const entered = parseFloat(raw);
                if (!entered || entered <= 0 || isNaN(entered)) {
                    inputAmt.classList.add('error');
                    inputAmt.focus();
                    return;
                }
                inputAmt.classList.remove('error');
                const userLabel = '$' + entered.toFixed(2).replace('.00', '');
                addMessage('user', 'Monto: ' + userLabel, { intent: { domain: 'FIN', action: 'clarify_amount' } });
                card.remove();
                state.pendingPlan = null;
                // Inject the amount into the original message (tier-3: "$25 compré café en efectivo")
                // then re-call /fin/plan with skip_candidate_clarification so we go straight to plan.
                const injected = _injectCandidateAmount(originalText, entered, null);
                handleFinPlan(injected, { domain: 'FIN' }, null, { skip_candidate_clarification: true });
            };

            btnApply.onclick = applyAmount;
            inputAmt.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); applyAmount(); }
            });

            inputRow.appendChild(inputAmt);
            inputRow.appendChild(btnApply);
            inputRow.appendChild(btnCancel);
            card.appendChild(inputRow);

            chatContainer.appendChild(card);
            scrollToBottom();

            // Focus immediately so user can type the amount right away
            setTimeout(() => inputAmt.focus(), 50);

            state.pendingPlan = {
                domain: 'FIN',
                containerId: cardId,
                planData: null,
                createdAt: Date.now(),
                kind: 'missing_amount_clarification',
                originalText: originalText,
            };
        }

        /**
         * Inject a $ sign into the original text for a confirmed amount.
         *
         * Three-tier strategy to guarantee the result always contains a proper
         * $ amount (preventing a re-entry into candidate-clarification):
         *
         * 1. Replace the exact confirmedAmount number in the text (happy path).
         * 2. If not found, replace the originalCandidateAmount number instead
         *    (user corrected the amount, e.g., said "30" when original had "25").
         * 3. Fallback: prepend "$N " to the original description.
         *
         * @param {string}  originalText            - The original user message
         * @param {number}  confirmedAmount          - Amount the user confirmed/provided
         * @param {number}  [originalCandidateAmount] - The candidate that was proposed
         */
        function _injectCandidateAmount(originalText, confirmedAmount, originalCandidateAmount) {
            // Preserve exact decimal cents: 30.50 → "30.5", 30 → "30", 12.75 → "12.75".
            // Math.round() was the prior implementation — it coerced 30.50 → 31, losing cents.
            const num = (confirmedAmount % 1 === 0)
                ? String(Math.round(confirmedAmount))
                : confirmedAmount.toFixed(2).replace(/0+$/, '');
            // Escape a literal dot so the tier-1 regex matches exactly (e.g. "30\.5")
            // rather than treating "." as a wildcard.
            const numPat = num.indexOf('.') >= 0 ? num.replace('.', '\\\\.') : num;

            // Tier 1: inject $ before the confirmed number if it appears verbatim in the text
            const tier1 = originalText.replace(
                new RegExp('(^|\\\\s)(' + numPat + ')(?=\\\\s|$)'),
                (match, prefix, n) => prefix + '$' + n
            );
            if (tier1 !== originalText) return tier1.trim();

            // Tier 2: replace the original candidate integer with the corrected $amount.
            // origNum uses Math.round because bare-number candidates are always integers.
            if (originalCandidateAmount != null) {
                const origNum = Math.round(originalCandidateAmount);
                const tier2 = originalText.replace(
                    new RegExp('(^|\\\\s)(' + origNum + ')(?=\\\\s|$)'),
                    (match, prefix) => prefix + '$' + num
                );
                if (tier2 !== originalText) return tier2.trim();
            }

            // Tier 3: prepend amount to preserve semantic context
            return ('$' + num + ' ' + originalText).trim();
        }

        async function handleFinPlan(text, intent, msgId = null, extraSessionCtx = {}) {
            const _msgId = msgId || 'msg_' + Date.now().toString(36);
            showTyping();

            try {
                const res = await fetch('/fin/plan', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify({
                        text: text,
                        session_id: state.conversationId,
                        session_context: { ...(state.finSessionContext || {}), ...extraSessionCtx }
                    })
                });
                
                const data = await res.json();
                hideTyping();
                
                if (res.status === 401) {
                    addMessage('assistant', 'Token invalido.', { ok: false, title: 'ERROR' });
                    clearToken();
                } else if (data.ok && data.kind === 'fin_plan' && data.total_items > 0) {
                    // Store session context for continuations
                    state.finSessionContext = data.session_context || {};
                    state.lastFinPlan = data;
                    
                    // Show chaperon message first (includes clarification if needed)
                    addMessage('assistant', safeText(data.message), { ok: true, title: data.needs_clarification ? 'FIN · Chaperón (aclarar)' : 'FIN · Chaperón' });
                    
                    // Render forms with "Guardar todo" functionality
                    renderPlanWithForms(data);
                    
                    // Note: pendingPlan is set inside renderPlanWithForms
                    
                } else if (data.needs_clarification) {
                    // Needs clarification but no items - ask user
                    state.finSessionContext = data.session_context || {};

                    const pendingClarif = data.session_context && data.session_context.pending_clarification;
                    const candidateAmount = pendingClarif && pendingClarif.candidate_amount;

                    if (candidateAmount) {
                        // Single clear numeric candidate → show button card.
                        // Always pass `text` (the actual user message sent to the backend) as
                        // originalText so that _injectCandidateAmount always has full context.
                        addMessage('assistant', safeText(data.message), { ok: true, title: 'FIN · clarificar' });
                        renderCandidateAmountCard(candidateAmount, data, text);
                        // pendingPlan is set inside renderCandidateAmountCard (kind: 'candidate_clarification')
                    } else if (pendingClarif && pendingClarif.kind === 'missing_amount') {
                        // No amount in message at all → structured inline input (preserves context).
                        // originalText comes from pending_clarification.original_text so that
                        // _injectCandidateAmount always has the full original user message.
                        addMessage('assistant', safeText(data.message), { ok: true, title: 'FIN · clarificar' });
                        renderMissingAmountCard(pendingClarif.original_text || text, data.clarification_prompt, intent);
                        // pendingPlan is set inside renderMissingAmountCard (kind: 'missing_amount_clarification')
                    } else {
                        // Multiple ambiguous candidates → text prompt (existing flow)
                        addMessage('assistant', safeText(data.message) + '\\n\\n' + safeText(data.clarification_prompt || ''), { ok: true, title: 'FIN · clarificar' });
                        // Set pendingPlan so the resolver can intercept the response
                        state.pendingPlan = {
                            domain: 'FIN',
                            containerId: null,  // No container yet
                            planData: data,
                            createdAt: Date.now(),
                            kind: 'clarification'
                        };
                        console.log('[PendingResolver] Set pendingPlan for clarification (no items)');
                    }
                    
                } else {
                    addMessage('assistant', safeText(data.message) || 'No se detectaron gastos.', { ok: false, title: 'FIN · error' });
                }
            } catch (e) {
                hideTyping();
                addMessage('assistant', 'Error de conexion: ' + e.message, { ok: false, title: 'ERROR' });
            }
            
            state.isLoading = false;
            updateSendButton();
        }
        
        // Render plan card with summary and item list
        function renderPlanCard(planData) {
            const card = document.createElement('div');
            card.className = 'expense-card plan-card';
            card.dataset.planId = planData.items[0]?.id || 'plan';
            
            // Header with count (escape backend message to prevent XSS)
            const headerHtml = '<div class="expense-header plan-header"><span class="plan-icon">📋</span> ' + escapeHtml(planData.message.split('\\n')[0]) + '</div>';
            
            // Items preview
            let itemsHtml = '<div class="plan-items">';
            planData.items.forEach((item, idx) => {
                const draft = item.draft_expense;
                const missingClass = item.missing_fields.length > 0 ? ' has-missing' : '';
                const isUnknownResp = draft.responsable === 'unknown' || !draft.responsable;
                itemsHtml += '<div class="plan-item' + missingClass + '">' +
                    '<span class="plan-item-num">' + (idx + 1) + '</span>' +
                    '<span class="plan-item-amount">' + escapeHtml(draft.moneda) + ' ' + draft.monto.toFixed(2) + '</span>' +
                    '<span class="plan-item-desc">' + escapeHtml(draft.descripcion || 'Gasto') + '</span>' +
                    '<span class="plan-item-resp' + (isUnknownResp ? ' is-unknown' : '') + '">' + (isUnknownResp ? '?' : escapeHtml(draft.responsable)) + '</span>' +
                '</div>';
            });
            itemsHtml += '</div>';
            
            // Actions
            const actionsHtml = '<div class="expense-actions plan-actions">' +
                '<button class="expense-btn cancel" onclick="cancelPlan(this)">Cancelar</button>' +
                '<button class="expense-btn confirm" onclick="confirmPlan(this)">Confirmar</button>' +
            '</div>';
            
            card.innerHTML = headerHtml + itemsHtml + actionsHtml;
            card.dataset.planJson = JSON.stringify(planData);
            
            chatContainer.appendChild(card);
            scrollToBottom();
        }
        
        // Render plan with editable forms directly (chaperon flow)
        function renderPlanWithForms(planData) {
            const items = planData.items || [];
            const isMulti = items.length > 1;
            const containerId = 'plan-container-' + Date.now();
            
            // Create container for all forms
            const container = document.createElement('div');
            container.id = containerId;
            container.className = 'plan-forms-container';
            container.dataset.mode = planData.mode || (isMulti ? 'multi' : 'single');
            container.dataset.total = items.length;
            container.dataset.planJson = JSON.stringify(planData);
            
            // Render forms
            items.forEach((item, idx) => {
                const draft = item.draft_expense;
                const formHtml = buildExpenseFormHtml(draft, item.id, idx, items.length, containerId);
                const form = document.createElement('div');
                form.innerHTML = formHtml;
                container.appendChild(form.firstElementChild);
            });
            
            // Add action bar for multi-expense
            if (isMulti) {
                const actionBar = document.createElement('div');
                actionBar.className = 'plan-action-bar';
                actionBar.innerHTML = 
                    '<button class="expense-btn cancel" onclick="cancelAllExpenses(\\'' + containerId + '\\')">Cancelar todo</button>' +
                    '<button class="expense-btn confirm save-all" onclick="saveAllExpenses(\\'' + containerId + '\\')">Confirmar y guardar todo (' + items.length + ')</button>';
                container.appendChild(actionBar);
            }
            
            chatContainer.appendChild(container);
            scrollToBottom();
            
            // Set pending plan for Pending Resolver
            state.pendingPlan = {
                domain: 'FIN',
                containerId: containerId,
                planData: planData,
                createdAt: Date.now(),
                kind: 'form'  // Distinguishes form-based flow from clarification flow
            };
            console.log('[PendingResolver] Set pendingPlan:', state.pendingPlan.containerId);
        }
        
        // Build expense form HTML
        function buildExpenseFormHtml(draft, itemId, idx, total, containerId) {
            const headerLabel = total > 1 ? 'Gasto ' + (idx + 1) + ' de ' + total : 'Gasto detectado';
            
            let warningHtml = '';
            if (draft.responsable === 'unknown') {
                warningHtml = '<div class="expense-warning">Por favor selecciona un responsable.</div>';
            }
            
            return '<div class="expense-card" data-item-id="' + itemId + '" data-container="' + containerId + '" data-idx="' + idx + '">' +
                '<div class="expense-header"><span class="amount">' + draft.moneda + ' ' + draft.monto.toFixed(2) + '</span> - ' + headerLabel + '</div>' +
                warningHtml +
                '<div class="expense-fields">' +
                    '<div class="expense-field"><label>Fecha</label><input type="date" class="expFecha" value="' + (draft.fecha || '') + '"></div>' +
                    '<div class="expense-field"><label>Monto</label><input type="number" step="0.01" class="expMonto" value="' + (draft.monto || '') + '"></div>' +
                    '<div class="expense-field"><label>Moneda</label><select class="expMoneda"><option value="USD"' + (draft.moneda === 'USD' ? ' selected' : '') + '>USD</option><option value="PAB"' + (draft.moneda === 'PAB' ? ' selected' : '') + '>PAB</option></select></div>' +
                    '<div class="expense-field"><label>Responsable</label><select class="expResponsable"><option value="Ana"' + (draft.responsable === 'Ana' ? ' selected' : '') + '>Ana</option><option value="Conejos"' + (draft.responsable === 'Conejos' ? ' selected' : '') + '>Conejos</option><option value="Jorge"' + (draft.responsable === 'Jorge' ? ' selected' : '') + '>Jorge</option><option value="eiProta"' + (draft.responsable === 'eiProta' ? ' selected' : '') + '>eiProta</option><option value="Proyectos"' + (draft.responsable === 'Proyectos' ? ' selected' : '') + '>Proyectos</option><option value="Hogar"' + (draft.responsable === 'Hogar' ? ' selected' : '') + '>Hogar</option><option value="unknown"' + (draft.responsable === 'unknown' ? ' selected' : '') + '>--</option></select></div>' +
                    '<div class="expense-field full-width"><label>Descripcion</label><input type="text" class="expDescripcion" value="' + (draft.descripcion || '').replace(/"/g, '&quot;') + '"></div>' +
                    '<div class="expense-field"><label>Categoria</label><input type="text" class="expCategoria" value="' + (draft.categoria || 'Otros') + '"></div>' +
                    '<div class="expense-field"><label>Metodo</label><select class="expMetodoPago"><option value=""' + (!draft.metodo_pago ? ' selected' : '') + '>--</option><option value="Efectivo"' + (draft.metodo_pago === 'Efectivo' ? ' selected' : '') + '>Efectivo</option><option value="Tarjeta"' + (draft.metodo_pago === 'Tarjeta' ? ' selected' : '') + '>Tarjeta</option><option value="Yappy"' + (draft.metodo_pago === 'Yappy' ? ' selected' : '') + '>Yappy</option><option value="Transferencia"' + (draft.metodo_pago === 'Transferencia' ? ' selected' : '') + '>Transferencia</option></select></div>' +
                    '<div class="expense-field"><label>ITBMS</label><select class="expItbms"><option value="true"' + (draft.itbms ? ' selected' : '') + '>Si</option><option value="false"' + (!draft.itbms ? ' selected' : '') + '>No</option></select></div>' +
                '</div>' +
                (total === 1 ? '<div class="expense-actions"><button class="expense-btn cancel" onclick="cancelExpenseForm(this)">Descartar</button><button class="expense-btn confirm" onclick="commitExpense(this)">Guardar</button></div>' : '') +
            '</div>';
        }
        
        // Cancel all expenses in container
        window.cancelAllExpenses = function(containerId) {
            const container = document.getElementById(containerId);
            if (container) {
                container.remove();
                addMessage('assistant', 'Gastos cancelados.', { ok: true, title: 'FIN · cancelado' });
            }
            // Clear pending plan
            if (state.pendingPlan && state.pendingPlan.containerId === containerId) {
                state.pendingPlan = null;
                state.lastFinPlan = null;
                console.log('[PendingResolver] Cleared pendingPlan (cancel)');
            }
        };
        
        // Save all expenses in container
        window.saveAllExpenses = async function(containerId) {
            const container = document.getElementById(containerId);
            if (!container) return;
            
            const cards = container.querySelectorAll('.expense-card:not(.committed)');
            if (cards.length === 0) return;
            
            // Disable all buttons
            container.querySelectorAll('.expense-btn').forEach(b => b.disabled = true);
            
            let successCount = 0;
            let errorCount = 0;
            const results = [];
            
            for (const card of cards) {
                const fecha = card.querySelector('.expFecha').value;
                const monto = parseFloat(card.querySelector('.expMonto').value) || 0;
                const moneda = card.querySelector('.expMoneda').value;
                const responsable = card.querySelector('.expResponsable').value;
                const descripcion = card.querySelector('.expDescripcion').value;
                const categoria = card.querySelector('.expCategoria').value;
                const metodoPago = card.querySelector('.expMetodoPago').value;
                const itbms = card.querySelector('.expItbms').value === 'true';
                
                // Validate
                if (!monto || monto <= 0) {
                    card.classList.add('has-error');
                    errorCount++;
                    results.push({ ok: false, card, error: 'Monto invalido' });
                    continue;
                }
                if (responsable === 'unknown') {
                    card.classList.add('has-error');
                    errorCount++;
                    results.push({ ok: false, card, error: 'Falta responsable' });
                    continue;
                }
                
                try {
                    const res = await fetch('/fin/commit', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Assistant-Token': state.token
                        },
                        body: JSON.stringify({
                            expense: {
                                fecha, monto, moneda, descripcion, categoria,
                                responsable, metodo_pago: metodoPago, itbms,
                                raw_segment: card.dataset.rawSegment || ''
                            },
                            session_id: state.conversationId
                        })
                    });
                    
                    const data = await res.json();
                    
                    if (data.ok && data.stored) {
                        card.innerHTML = '<div class="expense-success">✓ Guardado: ' + escapeHtml(moneda) + ' ' + monto.toFixed(2) + ' - ' + escapeHtml(descripcion) + ' (fila ' + data.row_number + ')</div>';
                        card.className = 'expense-card committed';
                        successCount++;
                        results.push({ ok: true, card, row: data.row_number });
                    } else {
                        card.classList.add('has-error');
                        errorCount++;
                        results.push({ ok: false, card, error: safeText(data.message || data.error) });
                    }
                } catch (e) {
                    card.classList.add('has-error');
                    errorCount++;
                    results.push({ ok: false, card, error: e.message });
                }
            }
            
            // Update action bar
            const actionBar = container.querySelector('.plan-action-bar');
            if (actionBar) {
                if (errorCount === 0) {
                    actionBar.innerHTML = '<div class="save-all-success">✓ ' + successCount + ' gastos guardados</div>';
                    // Clear pending plan on full success
                    if (state.pendingPlan && state.pendingPlan.containerId === containerId) {
                        state.pendingPlan = null;
                        state.lastFinPlan = null;
                        console.log('[PendingResolver] Cleared pendingPlan (commit success)');
                    }
                } else {
                    actionBar.innerHTML = '<div class="save-all-partial">' + successCount + ' guardados, ' + errorCount + ' con error</div>' +
                        '<button class="expense-btn confirm" onclick="saveAllExpenses(\\'' + containerId + '\\')">Reintentar</button>';
                }
            }
        };
        
        // Cancel plan - remove card
        window.cancelPlan = function(btn) {
            const card = btn.closest('.plan-card');
            if (card) {
                card.remove();
                addMessage('assistant', 'Plan cancelado.', { ok: true, title: 'FIN · cancelado' });
            }
        };
        
        // Confirm plan - show individual expense forms
        window.confirmPlan = function(btn) {
            const card = btn.closest('.plan-card');
            if (!card) return;
            
            const planData = JSON.parse(card.dataset.planJson || '{}');
            const items = planData.items || [];
            
            // Remove plan card
            card.remove();
            
            // Render individual expense cards for each item
            items.forEach((item, idx) => {
                const draft = item.draft_expense;
                renderExpenseFormFromPlan(draft, item.id, idx + 1, items.length);
            });
        };
        
        // Render expense form from plan item (for editing and committing)
        function renderExpenseFormFromPlan(draft, itemId, num, total) {
            const card = document.createElement('div');
            card.className = 'expense-card';
            card.dataset.itemId = itemId;
            
            // Header
            const headerLabel = total > 1 ? 'Gasto ' + num + ' de ' + total : 'Gasto detectado';
            const headerHtml = '<div class="expense-header"><span class="amount">' + escapeHtml(draft.moneda) + ' ' + draft.monto.toFixed(2) + '</span> - ' + headerLabel + '</div>';
            
            // Warning if missing responsable
            let warningHtml = '';
            if (draft.responsable === 'unknown') {
                warningHtml = '<div class="expense-warning">Por favor selecciona un responsable.</div>';
            }
            
            // Editable fields
            const fieldsHtml = '<div class="expense-fields">' +
                '<div class="expense-field"><label>Fecha</label><input type="date" class="expFecha" value="' + (draft.fecha || '') + '"></div>' +
                '<div class="expense-field"><label>Monto</label><input type="number" step="0.01" class="expMonto" value="' + (draft.monto || '') + '"></div>' +
                '<div class="expense-field"><label>Moneda</label><select class="expMoneda"><option value="USD"' + (draft.moneda === 'USD' ? ' selected' : '') + '>USD</option><option value="PAB"' + (draft.moneda === 'PAB' ? ' selected' : '') + '>PAB</option></select></div>' +
                '<div class="expense-field"><label>Responsable</label><select class="expResponsable"><option value="Ana"' + (draft.responsable === 'Ana' ? ' selected' : '') + '>Ana</option><option value="Conejos"' + (draft.responsable === 'Conejos' ? ' selected' : '') + '>Conejos</option><option value="Jorge"' + (draft.responsable === 'Jorge' ? ' selected' : '') + '>Jorge</option><option value="eiProta"' + (draft.responsable === 'eiProta' ? ' selected' : '') + '>eiProta</option><option value="Proyectos"' + (draft.responsable === 'Proyectos' ? ' selected' : '') + '>Proyectos</option><option value="Hogar"' + (draft.responsable === 'Hogar' ? ' selected' : '') + '>Hogar</option><option value="unknown"' + (draft.responsable === 'unknown' ? ' selected' : '') + '>--</option></select></div>' +
                '<div class="expense-field full-width"><label>Descripcion</label><input type="text" class="expDescripcion" value="' + (draft.descripcion || '').replace(/"/g, '&quot;') + '"></div>' +
                '<div class="expense-field"><label>Categoria</label><input type="text" class="expCategoria" value="' + (draft.categoria || 'Otros') + '"></div>' +
                '<div class="expense-field"><label>Metodo</label><select class="expMetodoPago"><option value=""' + (!draft.metodo_pago ? ' selected' : '') + '>--</option><option value="Efectivo"' + (draft.metodo_pago === 'Efectivo' ? ' selected' : '') + '>Efectivo</option><option value="Tarjeta"' + (draft.metodo_pago === 'Tarjeta' ? ' selected' : '') + '>Tarjeta</option><option value="Yappy"' + (draft.metodo_pago === 'Yappy' ? ' selected' : '') + '>Yappy</option><option value="Transferencia"' + (draft.metodo_pago === 'Transferencia' ? ' selected' : '') + '>Transferencia</option></select></div>' +
                '<div class="expense-field"><label>ITBMS</label><select class="expItbms"><option value="true"' + (draft.itbms ? ' selected' : '') + '>Si</option><option value="false"' + (!draft.itbms ? ' selected' : '') + '>No</option></select></div>' +
            '</div>';
            
            // Actions
            const actionsHtml = '<div class="expense-actions">' +
                '<button class="expense-btn cancel" onclick="cancelExpenseForm(this)">Descartar</button>' +
                '<button class="expense-btn confirm" onclick="commitExpense(this)">Guardar</button>' +
            '</div>';
            
            card.innerHTML = headerHtml + warningHtml + fieldsHtml + actionsHtml;
            card.dataset.rawSegment = draft.raw_segment || '';
            
            chatContainer.appendChild(card);
            scrollToBottom();
        }
        
        // Cancel expense form
        window.cancelExpenseForm = function(btn) {
            const card = btn.closest('.expense-card');
            if (card) {
                // Check if this was part of a single-expense pending plan
                const containerId = card.dataset.container;
                if (state.pendingPlan && state.pendingPlan.containerId === containerId) {
                    state.pendingPlan = null;
                    state.lastFinPlan = null;
                    console.log('[PendingResolver] Cleared pendingPlan (single cancel)');
                }
                card.remove();
            }
        };
        
        // Commit expense via /fin/commit
        window.commitExpense = async function(btn) {
            const card = btn.closest('.expense-card');
            if (!card) return;
            
            // Disable buttons
            card.querySelectorAll('.expense-btn').forEach(b => b.disabled = true);
            
            // Gather values
            const fecha = card.querySelector('.expFecha').value;
            const monto = parseFloat(card.querySelector('.expMonto').value) || 0;
            const moneda = card.querySelector('.expMoneda').value;
            const responsable = card.querySelector('.expResponsable').value;
            const descripcion = card.querySelector('.expDescripcion').value;
            const categoria = card.querySelector('.expCategoria').value;
            const metodoPago = card.querySelector('.expMetodoPago').value;
            const itbms = card.querySelector('.expItbms').value === 'true';
            
            // Validate
            if (!monto || monto <= 0) {
                alert('Por favor ingresa un monto valido.');
                card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
                return;
            }
            if (responsable === 'unknown') {
                alert('Por favor selecciona un responsable.');
                card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
                return;
            }
            
            try {
                const res = await fetch('/fin/commit', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify({
                        expense: {
                            fecha: fecha,
                            monto: monto,
                            moneda: moneda,
                            descripcion: descripcion,
                            categoria: categoria,
                            responsable: responsable,
                            metodo_pago: metodoPago,
                            itbms: itbms,
                            raw_segment: card.dataset.rawSegment || ''
                        },
                        session_id: state.conversationId
                    })
                });
                
                const data = await res.json();
                
                if (data.ok && data.stored) {
                    // Replace card with success message
                    card.innerHTML = '<div class="expense-success">✓ Guardado: ' + escapeHtml(moneda) + ' ' + monto.toFixed(2) + ' - ' + escapeHtml(descripcion) + ' (fila ' + data.row_number + ')</div>';
                    card.className = 'expense-card committed';
                    // Clear pending plan for single-expense
                    const containerId = card.dataset.container;
                    if (state.pendingPlan && state.pendingPlan.containerId === containerId) {
                        state.pendingPlan = null;
                        state.lastFinPlan = null;
                        console.log('[PendingResolver] Cleared pendingPlan (single commit)');
                    }
                } else {
                    alert('Error: ' + safeText(data.message || data.error || 'Unknown error'));
                    card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
                }
            } catch (e) {
                alert('Error de conexion: ' + e.message);
                card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
            }
        };

        // Handle FIN expense: parse and show editable card (LEGACY - still supported)
        async function handleFinExpense(text, intent) {
            showTyping();
            
            try {
                const res = await fetch('/fin/expense', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify({
                        text: text,
                        session_id: state.conversationId
                    })
                });
                
                const data = await res.json();
                hideTyping();
                
                if (res.status === 401) {
                    addMessage('assistant', 'Token invalido.', { ok: false, title: 'ERROR' });
                    clearToken();
                } else if (data.ok && data.expense) {
                    // Show expense card for confirmation
                    renderExpenseCard(data.expense, data.needs_confirmation, data.missing_fields, data.ambiguous_responsables || [], data.sheets_available);
                } else {
                    addMessage('assistant', safeText(data.message) || 'Error parsing expense', { ok: false, title: 'FIN · error' });
                }
            } catch (e) {
                hideTyping();
                addMessage('assistant', 'Error de conexion: ' + e.message, { ok: false, title: 'ERROR' });
            }
            
            state.isLoading = false;
            updateSendButton();
        }
        
        // Render expense card with editable fields
        function renderExpenseCard(expense, needsConfirm, missingFields, ambiguousResponsables, sheetsAvailable) {
            const card = document.createElement('div');
            card.className = 'expense-card';
            
            // Header with amount
            const amount = expense.monto ? expense.monto.toFixed(2) : '0.00';
            const headerHtml = '<div class="expense-header"><span class="amount">' + escapeHtml(expense.moneda) + ' ' + amount + '</span> - Gasto detectado</div>';
            
            // Warning if missing fields or ambiguous responsable
            let warningHtml = '';
            if (ambiguousResponsables && ambiguousResponsables.length > 1) {
                warningHtml = '<div class="expense-warning" style="background:#fff3e0;border-color:#ff9800;">Multiples responsables detectados: ' + escapeHtml(ambiguousResponsables.join(', ')) + '. Por favor selecciona uno.</div>';
            } else if (needsConfirm && missingFields && missingFields.length > 0) {
                warningHtml = '<div class="expense-warning">Faltan campos: ' + escapeHtml(missingFields.join(', ')) + '. Por favor completa los datos.</div>';
            }
            
            // Editable fields
            const fieldsHtml = '<div class="expense-fields">' +
                '<div class="expense-field"><label>Fecha</label><input type="date" id="expFecha" value="' + (expense.fecha || '') + '"></div>' +
                '<div class="expense-field"><label>Monto</label><input type="number" step="0.01" id="expMonto" value="' + (expense.monto || '') + '"></div>' +
                '<div class="expense-field"><label>Moneda</label><select id="expMoneda"><option value="USD"' + (expense.moneda === 'USD' ? ' selected' : '') + '>USD</option><option value="PAB"' + (expense.moneda === 'PAB' ? ' selected' : '') + '>PAB</option></select></div>' +
                '<div class="expense-field"><label>Responsable</label><select id="expResponsable"><option value="Ana"' + (expense.responsable === 'Ana' ? ' selected' : '') + '>Ana</option><option value="Conejos"' + (expense.responsable === 'Conejos' ? ' selected' : '') + '>Conejos</option><option value="Jorge"' + (expense.responsable === 'Jorge' ? ' selected' : '') + '>Jorge</option><option value="eiProta"' + (expense.responsable === 'eiProta' ? ' selected' : '') + '>eiProta</option><option value="Proyectos"' + (expense.responsable === 'Proyectos' ? ' selected' : '') + '>Proyectos</option><option value="Hogar"' + (expense.responsable === 'Hogar' ? ' selected' : '') + '>Hogar</option><option value="unknown"' + (expense.responsable === 'unknown' ? ' selected' : '') + '>--</option></select></div>' +
                '<div class="expense-field full-width"><label>Descripcion</label><input type="text" id="expDescripcion" value="' + (expense.descripcion || '').replace(/"/g, '&quot;') + '"></div>' +
                '<div class="expense-field"><label>Categoria</label><input type="text" id="expCategoria" value="' + (expense.categoria || 'otros') + '"></div>' +
                '<div class="expense-field"><label>ITBMS</label><select id="expItbms"><option value="true"' + (expense.itbms ? ' selected' : '') + '>Si</option><option value="false"' + (!expense.itbms ? ' selected' : '') + '>No</option></select></div>' +
            '</div>';
            
            // Actions
            const sheetsNote = sheetsAvailable ? '' : '<small style="color:#999;margin-right:8px;">Sheets no configurado</small>';
            const actionsHtml = '<div class="expense-actions">' + sheetsNote +
                '<button class="expense-btn cancel" onclick="cancelExpense(this)">Cancelar</button>' +
                '<button class="expense-btn confirm" onclick="confirmExpense(this)"' + (sheetsAvailable ? '' : ' disabled') + '>Confirmar y Guardar</button>' +
            '</div>';
            
            card.innerHTML = headerHtml + warningHtml + fieldsHtml + actionsHtml;
            card.dataset.rawText = expense.raw_text || '';
            
            chatContainer.appendChild(card);
            scrollToBottom();
        }
        
        // Cancel expense - remove card
        window.cancelExpense = function(btn) {
            const card = btn.closest('.expense-card');
            if (card) {
                card.remove();
                addMessage('assistant', 'Gasto cancelado.', { ok: true, title: 'FIN · cancelado' });
            }
        };
        
        // Confirm expense - send to /fin/expense/confirm
        window.confirmExpense = async function(btn) {
            const card = btn.closest('.expense-card');
            if (!card) return;
            
            // Disable buttons
            card.querySelectorAll('.expense-btn').forEach(b => b.disabled = true);
            
            // Gather values
            const fecha = card.querySelector('#expFecha').value;
            const monto = parseFloat(card.querySelector('#expMonto').value) || 0;
            const moneda = card.querySelector('#expMoneda').value;
            const responsable = card.querySelector('#expResponsable').value;
            const descripcion = card.querySelector('#expDescripcion').value;
            const categoria = card.querySelector('#expCategoria').value;
            const itbms = card.querySelector('#expItbms').value === 'true';
            
            // Validate
            if (!monto || monto <= 0) {
                alert('Por favor ingresa un monto valido.');
                card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
                return;
            }
            if (responsable === 'unknown') {
                alert('Por favor selecciona un responsable.');
                card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
                return;
            }
            
            try {
                const res = await fetch('/fin/expense/confirm', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify({
                        fecha: fecha,
                        monto: monto,
                        moneda: moneda,
                        descripcion: descripcion,
                        categoria: categoria,
                        responsable: responsable,
                        itbms: itbms,
                        session_id: state.conversationId
                    })
                });
                
                const data = await res.json();
                
                if (data.ok) {
                    // Replace card with success message
                    card.innerHTML = '<div class="expense-success">Gasto guardado en Sheets: ' + escapeHtml(moneda) + ' ' + monto.toFixed(2) + ' - ' + escapeHtml(descripcion) + '</div>';
                    state.messages.push({
                        id: generateUUID(),
                        type: 'fin_expense',
                        expense: data.expense,
                        ts: new Date().toISOString()
                    });
                } else {
                    alert('Error: ' + safeText(data.error?.message || data.error || 'Unknown error'));
                    card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
                }
            } catch (e) {
                alert('Error de conexion: ' + e.message);
                card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
            }
        };

        // Map intent domain to command prefix(CODE:, DOC:, or WORK_QUERY)
        function mapIntentToPrefix(text, intent) {
            const textLower = text.toLowerCase();
            const domain = intent ? intent.domain : null;
            
            // PRIORITY 1: Check for work query patterns (task questions)
            const workQueryPatterns = [
                /\\bqu[e\u00e9]\\s+tengo\\b/i,
                /\\btarea[s]?\\b/i,
                /\\burgente[s]?\\b/i,
                /\\bprioridad\\b/i,
                /\\bpendiente[s]?\\b/i,
                /\\bbloqueado[s]?\\b/i,
                /\\bhoy\\b/i,
                /\\binbox\\b/i,
                /\\bnext\\b/i,
                /\\bwaiting\\b/i,
                /\\bscheduled\\b/i,
                /\\besta\\s+semana\\b/i,
                /\\bpr[o\u00f3]xim[oa]s?\\b/i,
            ];
            
            // PRIORITY 2: Check for explicit doc request patterns
            const docRequestPatterns = [
                /\\bhaz\\s+(un\\s+)?doc(umento)?\\b/i,
                /\\bcrea(r)?\\s+(un\\s+)?doc\\b/i,
                /\\bredacta[r]?\\b/i,
                /\\bPOE\\b/,
                /\\bSOP\\b/,
                /\\binforme\\b/i,
                /\\bminuta\\b/i,
                /\\bacta\\b/i,
                /\\bensayo\\b/i,
                /\\bresumen\\s+en\\s+doc\\b/i,
                /\\bdocumento\\s+de\\b/i,
                /\\bdocumentar\\b/i,
            ];
            
            const isDocRequest = docRequestPatterns.some(p => p.test(textLower));
            const isWorkQuery = workQueryPatterns.some(p => p.test(textLower));
            
            // Work query takes priority UNLESS explicit doc request
            if (isWorkQuery && !isDocRequest) {
                return 'WORK_QUERY';
            }
            
            // Explicit doc request
            if (isDocRequest) {
                return 'DOC';
            }
            
            // Code patterns by domain
            if (domain === 'EIPROTA') {
                if (/m[o\u00f3]dulo|c[o\u00f3]digo|implementar|programar|simular/i.test(textLower)) {
                    return 'CODE';
                }
            } else if (domain === 'WORK' || domain === 'PRO_DIAG') {
                if (/script|automatizar|python|node|api/i.test(textLower)) {
                    return 'CODE';
                }
            }
            
            // Default to DOC
            return 'DOC';
        }
        
        // Build routed command with prefix
        function buildRoutedCommand(text, intent) {
            const prefix = mapIntentToPrefix(text, intent);
            return prefix + ': ' + text;
        }
        
        // Execute command via appropriate endpoint
        async function executeCommand(text, intent, overridden, msgId = null) {
            const _msgId = msgId || 'msg_' + Date.now().toString(36);
            showTyping();
            
            // Map intent to prefix (for CODE/DOC routing only)
            const prefix = mapIntentToPrefix(text, intent);
            
            // GUARD: Fallback to WORK_QUERY is PROHIBITED unless intent.operation is null/undefined
            // This prevents text heuristics from overriding explicit operation classification
            const hasOperation = intent?.operation !== null && intent?.operation !== undefined;
            if (prefix === 'WORK_QUERY') {
                if (hasOperation) {
                    // BLOCKED: intent has operation, do NOT fallback to WORK_QUERY
                    console.warn('[executeCommand] msg_id=' + _msgId + ', BLOCKED fallback to WORK_QUERY (intent.operation=' + intent.operation + ')');
                    // Continue to CODE/DOC routing below
                } else {
                    // ALLOWED: no operation in intent, fallback is safe
                    console.log('[executeCommand] msg_id=' + _msgId + ', ALLOWED fallback to WORK_QUERY (no operation)');
                    await executeWorkQuery(text, intent, overridden, _msgId);
                    return;
                }
            }
            
            console.log('[executeCommand] msg_id=' + _msgId + ', routing to /command (prefix=' + prefix + ')');
            
            // Build routed command for CODE/DOC
            const routedCommand = buildRoutedCommand(text, intent);
            
            try {
                const res = await fetch('/command/summary', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify({ 
                        text: routedCommand,
                        conversation_id: state.conversationId
                    })
                });
                
                const data = await res.json();
                hideTyping();
                
                if (res.status === 401) {
                    addMessage('assistant', 'Token invalido. Por favor ingresa un token valido.', { 
                        ok: false, 
                        title: 'ERROR · auth',
                        intent: intent,
                        intent_overridden: overridden,
                        routed_command: routedCommand
                    });
                    clearToken();
                } else {
                    data._originalText = text;
                    data.routed_command = routedCommand;
                    data.intent = intent;
                    data.intent_overridden = overridden;
                    addMessage('assistant', data.summary || 'Sin respuesta', data);
                }
            } catch (e) {
                hideTyping();
                addMessage('assistant', 'Error de conexion: ' + e.message, { 
                    ok: false, 
                    title: 'ERROR · network',
                    intent: intent,
                    intent_overridden: overridden,
                    routed_command: routedCommand
                });
            }
            
            state.isLoading = false;
            state.pendingMessage = null;
            state.pendingIntent = null;
            updateSendButton();
        }
        
        // Execute WORK_QUERY via /work/query endpoint (operation-based routing)
        async function executeWorkQuery(text, intent, overridden, msgId = null) {
            const _msgId = msgId || 'msg_' + Date.now().toString(36);
            try {
                const res = await fetch('/work/query', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify({
                        text: text,
                        session_context: {}
                    })
                });
                
                const data = await res.json();
                hideTyping();
                
                // [INSTRUMENTATION] Response received
                console.log('[Response] msg_id=' + _msgId + ', ok=' + data.ok + ', items=' + (data.items?.length || 0));
                console.log('[Renderer] msg_id=' + _msgId + ', branch=WorkQuery');
                
                if (res.status === 401) {
                    addMessage('assistant', 'Token invalido. Por favor ingresa un token valido.', {
                        ok: false,
                        title: 'ERROR · auth',
                        intent: intent,
                        intent_overridden: overridden,
                        route: 'WORK_QUERY'
                    });
                    clearToken();
                } else if (data.ok) {
                    // Format work query result as chat message
                    const items = data.items || [];
                    const count = items.length;
                    let summary = '';
                    
                    if (count === 0) {
                        summary = 'No encontre tareas que coincidan con tu consulta.';
                    } else {
                        summary = 'Tengo ' + count + ' tarea(s) activas:\\n';
                        items.slice(0, 10).forEach((item, i) => {
                            const title = item.title || item.Name || 'Sin titulo';
                            const status = item.status || '';
                            summary += (i + 1) + '. ' + title + (status ? ' [' + status + ']' : '') + '\\n';
                        });
                        if (count > 10) {
                            summary += '... y ' + (count - 10) + ' mas.';
                        }
                    }
                    
                    addMessage('assistant', summary, {
                        ok: true,
                        title: 'WORK · query',
                        items: items,
                        intent: intent,
                        intent_overridden: overridden,
                        route: 'WORK_QUERY',
                        _originalText: text,
                        _filters: data.query_filters
                    });
                } else {
                    // Error or unexpected response
                    const errorMsg = safeText(data.confirmation_message) || safeText(data.error) || 'Error consultando tareas';
                    addMessage('assistant', errorMsg, {
                        ok: false,
                        title: 'WORK · error',
                        intent: intent,
                        intent_overridden: overridden,
                        route: 'WORK_QUERY',
                        _originalText: text,
                        raw: data
                    });
                }
            } catch (e) {
                hideTyping();
                addMessage('assistant', 'Error de conexion: ' + e.message, {
                    ok: false,
                    title: 'ERROR · network',
                    intent: intent,
                    intent_overridden: overridden,
                    route: 'WORK_QUERY'
                });
            }
            
            state.isLoading = false;
            state.pendingMessage = null;
            state.pendingIntent = null;
            updateSendButton();
        }
        
        // Execute WORK_CREATE or WORK_DELETE (mutation with confirmation)
        async function executeWorkMutation(text, intent, overridden, msgId = null) {
            showTyping();
            const operation = intent ? intent.operation : 'WORK_CREATE';
            const _msgId = msgId || 'msg_' + Date.now().toString(36);
            
            try {
                // Call /command/summary to get the plan
                // IMPORTANT: Send operation to prevent backend re-classification
                const res = await fetch('/command/summary', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify({
                        text: text,
                        conversation_id: state.conversationId,
                        operation: operation  // Force backend to respect this operation
                    })
                });
                
                const data = await res.json();
                hideTyping();
                
                if (res.status === 401) {
                    addMessage('assistant', 'Token invalido.', { ok: false, title: 'ERROR · auth' });
                    clearToken();
                    return;
                }
                
                // PRIORITY CHECK: plan_confirmation_required MUST render ConfirmCard
                // This is the FIRST condition - no exceptions
                // NORMALIZE RESPONSE SHAPE - Support both formats:
                //   1. Full Response: data.output.type, data.output.plan
                //   2. SummaryResponse: data.details.type, data.details.plan
                //   3. Raw response: data.raw.output.type, data.raw.output.plan
                const responseStatus = data.status || '';  // "pending" | "ok" | "error"
                const outputType = data.output?.type || data.details?.type || data.raw?.output?.type || '';
                const plan = data.output?.plan || data.details?.plan || data.raw?.output?.plan || null;
                const contextId = data.context_id || data.raw?.context_id || '';
                const confirmationMessage = data.output?.confirmation_message || data.details?.confirmation_message || data.raw?.output?.confirmation_message || plan?.confirmation_message || '';
                const hasPlan = plan !== null;
                
                // [INSTRUMENTATION] Response received with normalized shape
                console.log('[Response] msg_id=' + _msgId + ', status=' + (responseStatus || 'null') + ', outputType=' + (outputType || 'null') + ', hasPlan=' + hasPlan + ', contextId=' + (contextId || 'null'));
                
                // BRANCH 1: status=pending + plan_confirmation_required -> ConfirmCard (NO EXCEPTIONS)
                // Per user requirement: IF status === "pending" AND output.type === "plan_confirmation_required"
                if (responseStatus === 'pending' && outputType === 'plan_confirmation_required' && plan && contextId) {
                    console.log('[Renderer] msg_id=' + _msgId + ', branch=ConfirmCard, action=' + (plan.action || 'unknown'));
                    renderWorkMutationConfirmation(text, plan, intent, overridden, contextId, _msgId, confirmationMessage);
                
                // BRANCH 2: validation_error -> Error message
                } else if (plan && plan.validation_error) {
                    console.log('[Renderer] msg_id=' + _msgId + ', branch=ValidationError');
                    // Validation error - show error message
                    addMessage('assistant', 'Error: ' + safeText(plan.validation_error), {
                        ok: false,
                        title: 'WORK · error',
                        intent: intent,
                        route: operation
                    });
                // BRANCH 3: work_update_preview -> conversational chat card
                } else if (outputType === 'work_update_proposal' || outputType === 'work_update_bulk_proposal') {
                    console.log('[Renderer] msg_id=' + _msgId + ', branch=WorkUpdateCard, outputType=' + outputType);
                    const details = data.details || data.output || {};
                    renderWorkUpdateCard(text, details, intent, _msgId);

                } else {
                    // BRANCH 4: Unexpected response - show generic message
                    console.log('[Renderer] msg_id=' + _msgId + ', branch=Generic, outputType=' + (outputType || 'null'));
                    addMessage('assistant', data.summary || 'Plan generado', {
                        ok: data.ok,
                        title: data.title || 'WORK',
                        intent: intent,
                        route: operation,
                        _originalText: text,
                        raw: data
                    });
                }
            } catch (e) {
                hideTyping();
                addMessage('assistant', 'Error de conexion: ' + e.message, {
                    ok: false,
                    title: 'ERROR · network',
                    intent: intent,
                    route: operation
                });
            }
            
            state.isLoading = false;
            state.pendingMessage = null;
            state.pendingIntent = null;
            updateSendButton();
        }
        
        // Render confirmation UI for WORK mutations (create/delete)
        function renderWorkMutationConfirmation(originalText, plan, intent, overridden, contextId, msgId, confirmationMessage) {
            const action = plan.action || 'WORK_CREATE';
            const preview = confirmationMessage || plan.preview || originalText;
            const filters = plan.filters || {};
            const isDelete = action.includes('DELETE');
            const riskLevel = plan.risk_level || (isDelete ? 'high' : 'medium');
            
            const card = document.createElement('div');
            card.className = 'expense-card work-confirm-card';
            card.dataset.planJson = JSON.stringify(plan);
            card.dataset.originalText = originalText;
            card.dataset.contextId = contextId || '';  // Store context_id for confirm flow
            card.dataset.msgId = msgId || '';
            
            console.log('[Renderer] msg_id=' + msgId + ', branch=ConfirmCard, contextId=' + (contextId || 'null'));
            
            // Header
            const headerLabel = isDelete ? 'Confirmar eliminacion' : 'Confirmar creacion';
            const headerIcon = isDelete ? '🗑️' : '✨';
            let headerHtml = '<div class="expense-header">' + headerIcon + ' ' + escapeHtml(headerLabel) + '</div>';
            
            // Preview with details
            let detailsHtml = '<div class="expense-fields" style="margin-bottom:12px;">';
            detailsHtml += '<div class="expense-field full-width"><strong>Accion:</strong> ' + escapeHtml(preview) + '</div>';
            
            if (isDelete) {
                const keywords = filters.keywords || [];
                const deleteAll = filters.delete_all || false;
                if (deleteAll) {
                    detailsHtml += '<div class="expense-field full-width" style="color:#ff3b30;">⚠️ Eliminar TODAS las tareas</div>';
                } else if (keywords.length > 0) {
                    detailsHtml += '<div class="expense-field full-width">Palabras clave: ' + escapeHtml(keywords.join(', ')) + '</div>';
                }
            } else {
                // Show CREATE fields
                if (filters.title) {
                    detailsHtml += '<div class="expense-field"><label>Titulo</label><span>' + escapeHtml(filters.title) + '</span></div>';
                }
                if (filters.project) {
                    detailsHtml += '<div class="expense-field"><label>Proyecto</label><span>' + escapeHtml(filters.project) + '</span></div>';
                }
                if (filters.status) {
                    detailsHtml += '<div class="expense-field"><label>Status</label><span>' + escapeHtml(filters.status) + '</span></div>';
                }
            }
            detailsHtml += '</div>';
            
            // Actions
            const riskClass = isDelete ? 'style="background:#ff3b30;"' : '';
            const confirmLabel = isDelete ? 'Eliminar' : 'Crear tarea';
            const actionsHtml = '<div class="expense-actions">' +
                '<button class="expense-btn cancel" onclick="cancelWorkConfirm(this)">Cancelar</button>' +
                '<button class="expense-btn confirm" ' + riskClass + ' onclick="executeWorkConfirm(this);">' + confirmLabel + '</button>' +
            '</div>';
            
            card.innerHTML = headerHtml + detailsHtml + actionsHtml;
            chatContainer.appendChild(card);
            scrollToBottom();
        }
        
        // Cancel WORK mutation confirmation
        window.cancelWorkConfirm = function(btn) {
            const card = btn.closest('.work-confirm-card');
            if (card) {
                const msgId = card.dataset.msgId || '';
                const contextId = card.dataset.contextId || '';
                console.log('[Renderer] msg_id=' + msgId + ', branch=Cancel, contextId=' + contextId);
                card.remove();
                addMessage('assistant', 'Operacion cancelada.', { ok: true, title: 'WORK · cancelado' });
            }
        };
        
        // Execute confirmed WORK mutation via context_id (NO re-classification)
        window.executeWorkConfirm = async function(btn) {
            const card = btn.closest('.work-confirm-card');
            if (!card) return;
            
            const contextId = card.dataset.contextId || '';
            const msgId = card.dataset.msgId || '';
            const planJson = card.dataset.planJson || '{}';
            const plan = JSON.parse(planJson);
            const action = plan.action || '';
            
            // [INSTRUMENTATION] Confirm execution
            console.log('[Confirm] msg_id=' + msgId + ', endpoint=/command, context_id=' + contextId + ', confirm=true');
            
            // Validate context_id exists
            if (!contextId) {
                console.error('[Confirm] ERROR: Missing context_id, falling back to direct endpoint');
                // Fallback to old behavior if context_id is missing (shouldn't happen)
                await executeWorkConfirmLegacy(btn, plan);
                return;
            }
            
            // Disable buttons during execution
            card.querySelectorAll('.expense-btn').forEach(b => b.disabled = true);
            
            try {
                // POST /command with confirm=true + context_id (NO re-classification)
                const res = await fetch('/command', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify({
                        context_id: contextId,
                        confirm: true
                    })
                });
                
                const data = await res.json();
                
                // Remove card
                card.remove();
                
                // Normalize output
                const output = data.output || {};
                const outputType = output.type || '';
                
                // [INSTRUMENTATION] Confirm response
                console.log('[ConfirmResponse] msg_id=' + msgId + ', output.type=' + outputType + ', error=' + (data.error?.message || 'null'));
                
                if (data.status === 'ok') {
                    if (outputType === 'work_create') {
                        addMessage('assistant', '✓ Tarea creada: ' + safeText(output.title || plan.filters?.title || ''), {
                            ok: true,
                            title: 'WORK · creado',
                            page_id: output.page_id,
                            url: output.url
                        });
                    } else if (outputType === 'work_delete') {
                        const count = output.deleted_count || output.archived_count || 0;
                        addMessage('assistant', '✓ ' + count + ' tarea(s) eliminada(s)', {
                            ok: true,
                            title: 'WORK · eliminado',
                            deleted_count: count
                        });
                    } else {
                        // Generic success
                        addMessage('assistant', '✓ Operacion completada', {
                            ok: true,
                            title: 'WORK · ok'
                        });
                    }
                } else {
                    const errorMsg = data.error?.message || output.error || 'Error desconocido';
                    addMessage('assistant', 'Error: ' + safeText(errorMsg), {
                        ok: false,
                        title: 'WORK · error'
                    });
                }
            } catch (e) {
                card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
                console.log('[ConfirmResponse] msg_id=' + msgId + ', error=network: ' + e.message);
                addMessage('assistant', 'Error: ' + e.message, {
                    ok: false,
                    title: 'ERROR · network'
                });
            }
        };
        
        // Legacy confirm for fallback (if context_id missing - shouldn't happen in normal flow)
        async function executeWorkConfirmLegacy(btn, plan) {
            const card = btn.closest('.work-confirm-card');
            if (!card) return;
            
            const action = plan.action || '';
            const filters = plan.filters || {};
            
            card.querySelectorAll('.expense-btn').forEach(b => b.disabled = true);
            
            try {
                let endpoint, body;
                
                if (action.includes('CREATE')) {
                    endpoint = '/work/create';
                    body = {
                        title: filters.title || '',
                        project: filters.project || null,
                        status: filters.status || 'INBOX',
                        load: filters.load || null,
                        due: filters.due || null,
                        notes: filters.notes || null,
                        plan: plan
                    };
                } else if (action.includes('DELETE')) {
                    endpoint = '/work/delete';
                    body = {
                        keywords: filters.keywords || [],
                        delete_all: filters.delete_all || false,
                        delete_mode: filters.delete_mode || 'archive',
                        plan: plan
                    };
                } else {
                    throw new Error('Unknown action: ' + action);
                }
                
                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify(body)
                });
                
                const data = await res.json();
                card.remove();
                
                if (data.ok) {
                    if (action.includes('CREATE')) {
                        addMessage('assistant', '✓ Tarea creada: ' + safeText(data.title || filters.title), {
                            ok: true,
                            title: 'WORK · creado',
                            page_id: data.page_id,
                            url: data.url
                        });
                    } else {
                        const count = data.deleted_count || data.archived_count || 0;
                        addMessage('assistant', '✓ ' + count + ' tarea(s) eliminada(s)', {
                            ok: true,
                            title: 'WORK · eliminado',
                            deleted_count: count
                        });
                    }
                } else {
                    addMessage('assistant', 'Error: ' + safeText(data.error || 'Error desconocido'), {
                        ok: false,
                        title: 'WORK · error'
                    });
                }
            } catch (e) {
                card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
                addMessage('assistant', 'Error: ' + e.message, {
                    ok: false,
                    title: 'ERROR · network'
                });
            }
        }
        
        // Add message with intent chip
        function addMessageWithIntent(type, content, intent, overridden) {
            emptyState.style.display = 'none';
            
            const msg = document.createElement('div');
            msg.className = 'message ' + type;
            
            const bubble = document.createElement('div');
            bubble.className = 'bubble';
            bubble.textContent = safeText(content);
            
            // Add intent chip for user messages
            if (type === 'user' && intent) {
                const chip = createIntentChip(intent, overridden);
                bubble.appendChild(chip);
            }
            
            msg.appendChild(bubble);
            chatContainer.appendChild(msg);
            scrollToBottom();
            
            state.messages.push({ 
                id: generateUUID(),
                type, 
                content, 
                intent: intent || null,
                intent_overridden: overridden,
                ts: new Date().toISOString() 
            });
            
            return msg;
        }
        
        // Create intent chip element
        function createIntentChip(intent, overridden) {
            const chip = document.createElement('div');
            chip.className = 'intent-chip' + (overridden ? ' overridden' : '');
            
            // Domain badge
            const domain = document.createElement('span');
            domain.className = 'chip-domain';
            domain.textContent = safeText(intent.domain);
            chip.appendChild(domain);
            
            // Show action if present and meaningful (Plan-first)
            const action = intent.action || intent.operation;
            if (action && action !== 'COMMAND') {
                const actionBadge = document.createElement('span');
                actionBadge.className = 'chip-action';
                actionBadge.textContent = '→ ' + safeText(action);
                actionBadge.style.color = '#007aff';
                actionBadge.style.fontWeight = '600';
                chip.appendChild(actionBadge);
            }
            
            // Show primary filter if present
            const filters = intent.filters || {};
            const primaryFilter = filters.project || filters.status || filters.title_keyword;
            if (primaryFilter) {
                const filterBadge = document.createElement('span');
                filterBadge.className = 'chip-filter';
                filterBadge.style.background = 'rgba(52, 199, 89, 0.15)';
                filterBadge.style.color = '#34c759';
                filterBadge.style.padding = '2px 6px';
                filterBadge.style.borderRadius = '4px';
                filterBadge.style.fontSize = '10px';
                if (filters.project) {
                    filterBadge.textContent = 'proyecto=' + safeText(filters.project);
                } else if (filters.status) {
                    const statusVal = Array.isArray(filters.status) ? filters.status.join(',') : filters.status;
                    filterBadge.textContent = 'status=' + safeText(statusVal);
                } else if (filters.title_keyword) {
                    filterBadge.textContent = 'keyword=' + safeText(filters.title_keyword);
                }
                chip.appendChild(filterBadge);
            }
            
            // Type and impact (secondary info)
            if (intent.type) {
                const type = document.createElement('span');
                type.textContent = safeText(intent.type);
                chip.appendChild(type);
            }
            
            if (intent.impact) {
                const impact = document.createElement('span');
                impact.textContent = safeText(intent.impact);
                chip.appendChild(impact);
            }
            
            // Confidence
            if (intent.confidence !== undefined) {
                const conf = document.createElement('span');
                conf.className = 'chip-conf';
                conf.textContent = Math.round(intent.confidence * 100) + '%';
                chip.appendChild(conf);
            }
            
            // Override badge
            if (overridden) {
                const badge = document.createElement('span');
                badge.textContent = '(override)';
                badge.style.fontStyle = 'italic';
                badge.style.color = '#ff9500';
                chip.appendChild(badge);
            }
            
            return chip;
        }
        
        // Show warning chip on a message
        function showWarningChip(msgEl, text) {
            const bubble = msgEl.querySelector('.bubble');
            if (!bubble) return;
            
            const warning = document.createElement('div');
            warning.className = 'warning-chip';
            warning.textContent = '⚠ ' + text;
            bubble.insertBefore(warning, bubble.firstChild);
        }
        
        // Build a <div class="expense-field"> containing a labeled <select>.
        // opts: string[] from Notion; currentVal: pre-select current; proposedVal: pre-select proposed.
        // Priority: proposed > current > blank placeholder (never silently auto-selects first option).
        function _buildNotionSelect(fieldName, opts, currentVal, proposedVal) {
            const fallbacks = {
                domain:  ['General', 'THCyE', 'Proyectos', 'Hogar'],
                project: [],
                status:  ['SCHEDULED', 'WAITING', 'DONE', 'CANCELLED'],
            };
            const options = (opts && opts.length > 0) ? opts : (fallbacks[fieldName] || []);
            const wrap = document.createElement('div');
            wrap.className = 'expense-field';
            const lbl = document.createElement('label');
            lbl.textContent = fieldName.charAt(0).toUpperCase() + fieldName.slice(1);
            const sel = document.createElement('select');
            sel.name = fieldName;

            // Determine which value to pre-select (proposed > current; null/undefined = none).
            const normalizeVal = v => (v && typeof v === 'string' && v.trim()) ? v.trim().toLowerCase() : null;
            const targetVal = normalizeVal(proposedVal) || normalizeVal(currentVal);

            // If there's no value to select, prepend a blank placeholder so the browser
            // doesn't silently pick the first real option and mislead the user.
            if (!targetVal) {
                const placeholder = document.createElement('option');
                placeholder.value = '';
                placeholder.textContent = '— sin valor —';
                placeholder.selected = true;
                sel.appendChild(placeholder);
            }

            options.forEach(opt => {
                const o = document.createElement('option');
                o.value = opt;
                o.textContent = opt;
                if (targetVal && opt.toLowerCase() === targetVal) o.selected = true;
                sel.appendChild(o);
            });
            wrap.appendChild(lbl);
            wrap.appendChild(sel);
            return { wrap, sel };
        }

        // POST /command with confirm=true for WORK_UPDATE confirmation.
        // Replaces executeCommand() which re-classifies text instead of confirming.
        async function executeWorkUpdateConfirm(card, contextId, originalText, applied_changes, isBulk) {
            card.querySelectorAll('.expense-btn').forEach(b => b.disabled = true);
            try {
                const body = { context_id: contextId, confirm: true, applied_changes };
                if (isBulk) {
                    body.selected_notion_page_ids = Array.from(
                        card.querySelectorAll('input[type=checkbox]:checked')
                    ).map(cb => cb.value);
                }
                const res = await fetch('/command', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Assistant-Token': state.token
                    },
                    body: JSON.stringify(body)
                });
                const data = await res.json();
                card.remove();
                const output = data.output || {};
                const outputType = output.type || '';
                if (data.status === 'ok') {
                    if (outputType === 'work_update_result') {
                        addMessage('assistant', '\u2713 Tarea actualizada: ' + safeText(output.title || ''), {
                            ok: true,
                            title: 'WORK \u00b7 actualizado',
                        });
                    } else if (outputType === 'work_update_bulk_result') {
                        addMessage('assistant', '\u2713 ' + (output.updated_count || 0) + ' tarea(s) actualizada(s)', {
                            ok: true,
                            title: 'WORK \u00b7 bulk actualizado',
                        });
                    } else {
                        addMessage('assistant', '\u2713 Actualizaci\u00f3n completada', { ok: true, title: 'WORK \u00b7 ok' });
                    }
                } else {
                    const errorMsg = data.error?.message || output.error || 'Error desconocido';
                    addMessage('assistant', 'Error: ' + safeText(errorMsg), { ok: false, title: 'WORK \u00b7 error' });
                }
            } catch (e) {
                card.querySelectorAll('.expense-btn').forEach(b => b.disabled = false);
                addMessage('assistant', 'Error de red: ' + e.message, { ok: false, title: 'ERROR \u00b7 network' });
            }
        }

        // Render a conversational message + inline update form card for WORK_UPDATE proposals.
        function renderWorkUpdateCard(originalText, details, intent, msgId) {
            const isBulk = details.type === 'work_update_bulk_proposal';
            const notionOpts = details.options && details.options.options ? details.options.options : {};
            const currentVals = details.current_values || {};

            // Extract proposed value per field from proposed_changes list (singular path)
            const proposedMap = {};
            if (Array.isArray(details.proposed_changes)) {
                details.proposed_changes.forEach(c => {
                    if (c && c.field) proposedMap[c.field] = c.new_value;
                });
            }
            // Bulk: applied_changes is already a flat dict
            if (isBulk && details.applied_changes) {
                Object.assign(proposedMap, details.applied_changes);
            }

            // --- Conversational message bubble ---
            const convText = isBulk
                ? 'Encontré ' + (details.match_count || details.matches.length) + ' tareas. Confirma o ajusta los cambios abajo.'
                : 'Encontré la tarea \u201c' + escapeHtml(details.title || '') + '\u201d. Confirma o ajusta los cambios abajo.';
            addMessage('assistant', convText, {
                title: isBulk ? 'WORK \u00b7 bulk update' : 'WORK \u00b7 update',
                ok: true,
                intent: intent,
            });

            // --- Inline update card ---
            const card = document.createElement('div');
            card.className = 'expense-card work-update-card';

            // Header
            const headerLabel = isBulk
                ? 'Actualizar ' + (details.match_count || '') + ' tareas'
                : 'Actualizar tarea';
            card.innerHTML = '<div class="expense-header">\u270F\uFE0F ' + escapeHtml(headerLabel) + '</div>';

            // Warning for high-risk bulk
            if (details.warning) {
                const warn = document.createElement('div');
                warn.className = 'expense-warning';
                warn.textContent = details.warning;
                card.appendChild(warn);
            }

            // Bulk: task checklist
            if (isBulk && Array.isArray(details.matches) && details.matches.length > 0) {
                const ul = document.createElement('ul');
                ul.className = 'update-task-list';
                details.matches.forEach(m => {
                    const li = document.createElement('li');
                    const cb = document.createElement('input');
                    cb.type = 'checkbox';
                    cb.value = m.notion_page_id;
                    cb.id = 'upd_' + m.notion_page_id;
                    cb.checked = true;   // pre-select all (user confirmed bulk)
                    const lbl = document.createElement('label');
                    lbl.htmlFor = cb.id;
                    lbl.textContent = (m.title || '(sin título)') + ' [' + (m.status || '') + ']';
                    li.appendChild(cb);
                    li.appendChild(lbl);
                    ul.appendChild(li);
                });
                card.appendChild(ul);
            }

            // Singular: show task title row
            if (!isBulk && details.title) {
                const titleRow = document.createElement('div');
                titleRow.className = 'expense-fields';
                titleRow.style.marginBottom = '8px';
                titleRow.innerHTML = '<div class="expense-field full-width"><label>Tarea</label><span>' + escapeHtml(details.title) + '</span></div>';
                card.appendChild(titleRow);
            }

            // Dropdown grid
            const grid = document.createElement('div');
            grid.className = 'update-field-grid';
            const { wrap: domainWrap, sel: domainSel } = _buildNotionSelect('domain',  notionOpts.domain,  currentVals.domain,  proposedMap.domain);
            const { wrap: projectWrap, sel: projectSel } = _buildNotionSelect('project', notionOpts.project, currentVals.project, proposedMap.project);
            const { wrap: statusWrap,  sel: statusSel  } = _buildNotionSelect('status',  notionOpts.status,  currentVals.status,  proposedMap.status);
            grid.appendChild(domainWrap);
            grid.appendChild(projectWrap);
            grid.appendChild(statusWrap);
            card.appendChild(grid);

            // Action buttons
            const actions = document.createElement('div');
            actions.className = 'expense-actions';

            const btnCancel = document.createElement('button');
            btnCancel.className = 'expense-btn cancel';
            btnCancel.textContent = 'Cancelar';
            btnCancel.onclick = () => {
                card.remove();
                state.pendingMessage = null;
                state.pendingIntent = null;
            };

            const btnConfirm = document.createElement('button');
            btnConfirm.className = 'expense-btn confirm';
            btnConfirm.textContent = isBulk ? 'Confirmar actualización bulk' : 'Confirmar actualización';
            btnConfirm.onclick = () => {
                const applied_changes = {};
                if (domainSel.value) applied_changes.domain  = domainSel.value;
                if (projectSel.value) applied_changes.project = projectSel.value;
                if (statusSel.value) applied_changes.status  = statusSel.value;
                executeWorkUpdateConfirm(card, details.context_id, originalText, applied_changes, isBulk);
            };

            actions.appendChild(btnCancel);
            actions.appendChild(btnConfirm);
            card.appendChild(actions);

            chatContainer.appendChild(card);
            scrollToBottom();
        }

        // Show confirmation panel
        function showConfirmationPanel(intent) {
            // Remove any existing confirmation panel
            const existing = document.querySelector('.confirm-panel');
            if (existing) existing.remove();

            const panel = document.createElement('div');
            panel.className = 'confirm-panel';
            panel.id = 'confirmPanel';

            const text = document.createElement('div');
            text.className = 'confirm-text';
            let details = intent && intent.details ? intent.details : {};

            // Default generic confirm panel
            text.innerHTML = 'Dominio detectado: <strong>' + escapeHtml(intent.domain) + '</strong> (' + 
                Math.round(intent.confidence * 100) + '% confianza)<br>' +
                '<small>¿Como quieres proceder?</small>';
            panel.appendChild(text);
            const actions = document.createElement('div');
            actions.className = 'confirm-actions';
            const btnSend = document.createElement('button');
            btnSend.className = 'confirm-btn primary';
            btnSend.textContent = 'Enviar como esta';
            btnSend.onclick = () => confirmSend(false);
            actions.appendChild(btnSend);
            const btnChat = document.createElement('button');
            btnChat.className = 'confirm-btn';
            btnChat.textContent = 'Solo chat';
            btnChat.onclick = () => confirmChatOnly();
            actions.appendChild(btnChat);
            const btnChange = document.createElement('button');
            btnChange.className = 'confirm-btn';
            btnChange.textContent = 'Cambiar dominio';
            btnChange.onclick = () => showDomainSelector();
            actions.appendChild(btnChange);
            panel.appendChild(actions);
            chatContainer.appendChild(panel);
            scrollToBottom();
        }
        
        // Confirm and send
        function confirmSend(overridden, newDomain = null) {
            hideConfirmationPanel();

            let intent = state.pendingIntent;
            const message = state.pendingMessage;
            if (overridden && newDomain) {
                intent = { ...intent, domain: newDomain, needs_confirmation: false };
            }

            state.isLoading = true;
            updateSendButton();

            // FIN domain (manual override or operation) must go through handleFinPlan,
            // not executeCommand, so the /fin/plan pipeline is used.
            if (intent && (intent.operation === 'FIN_EXPENSE' || intent.domain === 'FIN')) {
                const msgId = 'msg_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 4);
                handleFinPlan(message, intent, msgId);
                return;
            }

            executeCommand(message, intent, overridden);
        }
        
        // Chat only - no execution
        function confirmChatOnly() {
            hideConfirmationPanel();
            addMessage('assistant', 'OK (chat-only) - Mensaje registrado sin ejecutar.', { 
                ok: true, 
                title: 'CHAT · registro',
                intent: state.pendingIntent,
                intent_overridden: false
            });
            state.pendingMessage = null;
            state.pendingIntent = null;
        }
        
        // Hide confirmation panel
        function hideConfirmationPanel() {
            const panel = document.getElementById('confirmPanel');
            if (panel) panel.remove();
        }
        
        // Show domain selector modal
        function showDomainSelector() {
            domainModal.classList.remove('hidden');
        }
        
        // Hide domain selector modal
        function hideDomainSelector() {
            domainModal.classList.add('hidden');
        }
        
        // Select domain
        function selectDomain(domain) {
            hideDomainSelector();
            hideConfirmationPanel();
            confirmSend(true, domain);
        }
        
        // Set mode
        function setMode(mode) {
            state.mode = mode;
            localStorage.setItem('assistant_os.mode', mode);
            
            modeBtns.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.mode === mode);
            });
        }
        
        // Initialize mode UI
        function initModeUI() {
            modeBtns.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.mode === state.mode);
                btn.addEventListener('click', () => setMode(btn.dataset.mode));
            });
        }
        
        // New session
        function newSession() {
            state.conversationId = generateUUID();
            localStorage.setItem('assistant_os.conversation_id', state.conversationId);
            updateSessionDisplay();
            clearChatUI();
        }
        
        // Copy session ID to clipboard
        async function copySession() {
            try {
                await navigator.clipboard.writeText(state.conversationId);
                showToast('Copied!');
            } catch (e) {
                // Fallback for older browsers
                const ta = document.createElement('textarea');
                ta.value = state.conversationId;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                showToast('Copied!');
            }
        }
        
        // Show toast notification
        function showToast(message) {
            toast.textContent = message;
            toast.classList.add('show');
            setTimeout(() => {
                toast.classList.remove('show');
            }, 2000);
        }
        
        // Join session modal
        function showJoinModal() {
            joinInput.value = '';
            joinError.classList.remove('show');
            joinModal.classList.remove('hidden');
            joinInput.focus();
        }
        
        function hideJoinModal() {
            joinModal.classList.add('hidden');
        }
        
        async function joinSession() {
            const newId = joinInput.value.trim();
            
            // Validate: not empty and at least 7 chars
            if (!newId || newId.length < 7) {
                joinError.classList.add('show');
                return;
            }
            
            joinError.classList.remove('show');
            
            // Set new conversation ID
            state.conversationId = newId;
            localStorage.setItem('assistant_os.conversation_id', newId);
            updateSessionDisplay();
            
            // Clear UI and load history
            clearChatUI();
            hideJoinModal();
            
            if (state.token) {
                await loadHistory();
            }
        }
        
        // Clear chat (UI only)
        function clearChat() {
            clearChatUI();
        }
        
        // Export chat
        function exportChat() {
            if (state.messages.length === 0) return;
            
            const exportData = {
                conversation_id: state.conversationId,
                exported_at: new Date().toISOString(),
                messages: state.messages
            };
            
            const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'assistant_chat_' + state.conversationId.substring(0, 8) + '_' + new Date().toISOString().slice(0, 10) + '.json';
            a.click();
            URL.revokeObjectURL(url);
        }
        
        // Event listeners
        messageInput.addEventListener('input', () => {
            autoResize();
            updateSendButton();
        });
        
        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        
        btnSend.addEventListener('click', sendMessage);
        btnClear.addEventListener('click', clearChat);
        btnExport.addEventListener('click', exportChat);
        btnToken.addEventListener('click', clearToken);
        btnNewSession.addEventListener('click', newSession);
        btnReload.addEventListener('click', loadHistory);
        btnCopySession.addEventListener('click', copySession);
        btnJoinSession.addEventListener('click', showJoinModal);
        btnSaveToken.addEventListener('click', saveToken);
        btnCancelJoin.addEventListener('click', hideJoinModal);
        btnConfirmJoin.addEventListener('click', joinSession);
        btnCancelDomain.addEventListener('click', hideDomainSelector);
        
        // Domain grid click handlers
        domainGrid.querySelectorAll('.domain-option').forEach(opt => {
            opt.addEventListener('click', () => selectDomain(opt.dataset.domain));
        });
        
        tokenInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') saveToken();
        });
        
        joinInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') joinSession();
            if (e.key === 'Escape') hideJoinModal();
        });
        
        // Initialize mode UI
        initModeUI();
        
        // Start
        init();
    </script>
</body>
</html>'''

