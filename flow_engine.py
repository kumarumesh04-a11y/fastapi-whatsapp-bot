import logging
import json
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class FlowEngine:
    def __init__(self):
        pass
    
    async def process(self, phone: str, name: str, message: str, interactive_data: dict, 
                     client: Dict, flow_config: Dict, session: Dict, wa: Any):
        """Main entry point for processing messages through configured flow"""
        
        current_step = session.get('current_step', 'welcome')
        responses = session.get('responses', {})
        
        # Handle START_ trigger as fresh conversation
        if message and message.startswith("START_"):
            logger.info(f"START trigger detected, resetting session for {phone}")
            from database import update_user_session
            update_user_session(phone, {
                'client_id': client['id'],
                'current_step': 'welcome',
                'responses': {}
            })
            await self._send_welcome(phone, name, client, flow_config, wa)
            return
        
        # Handle welcome/start keywords
        if message and message.lower() in ['hi', 'hello', 'start', 'hey']:
            await self._send_welcome(phone, name, client, flow_config, wa)
            return
        
        # Handle button replies
        if interactive_data and interactive_data.get("type") == "button_reply":
            button_id = interactive_data.get("button_reply", {}).get("id")
            button_title = interactive_data.get("button_reply", {}).get("title")
            
            # Store response
            responses[current_step] = {
                'value': button_title,
                'id': button_id
            }
            
            # Determine next step
            next_step = self._get_next_step(flow_config, current_step, button_id)
            
        # Handle text input
        elif message:
            # Special handling for contact info step
            if current_step == 'contact_info' or self._is_contact_step(flow_config, current_step):
                parsed = self._parse_contact_info(message)
                if parsed:
                    responses['name'] = parsed.get('name', name)
                    responses['phone'] = parsed.get('phone', phone)
                else:
                    await wa.send_text(phone, "Please share in format: Name, Phone\nExample: Rahul, 919876543210")
                    return
            
            # Regular text response
            else:
                responses[current_step] = {
                    'value': message,
                    'id': message.lower().replace(' ', '_')
                }
            
            next_step = self._get_next_step(flow_config, current_step, None)
        
        else:
            # Unknown input, repeat current step
            await self._send_step_question(phone, current_step, flow_config, wa)
            return
        
        # Check if flow complete
        if next_step == 'complete' or not next_step:
            await self._complete_flow(phone, client, flow_config, responses, wa)
            return
        
        # Send next question
        await self._send_step_question(phone, next_step, flow_config, wa)
        
        # Update session
        from database import update_user_session
        update_user_session(phone, {
            'client_id': client['id'],
            'current_step': next_step,
            'responses': responses
        })
    
    async def _send_welcome(self, phone: str, name: str, client: Dict, flow_config: Dict, wa: Any):
        """Send welcome message and first question"""
        welcome_msg = flow_config.get('welcome_message', f"Welcome to {client['company_name']}!")
        welcome_msg = welcome_msg.replace('{name}', name)
        
        await wa.send_text(phone, welcome_msg)
        
        # Get first step
        steps = flow_config.get('steps', [])
        if steps:
            first_step = steps[0]['id']
            await self._send_step_question(phone, first_step, flow_config, wa)
            
            from database import update_user_session
            update_user_session(phone, {
                'client_id': client['id'],
                'current_step': first_step,
                'responses': {}
            })
    
    async def _send_step_question(self, phone: str, step_id: str, flow_config: Dict, wa: Any):
        """Send question for current step"""
        step = self._get_step_by_id(flow_config, step_id)
        if not step:
            return
        
        question_text = step.get('text', 'Please respond:')
        step_type = step.get('type', 'text')
        
        if step_type == 'single_choice':
            options = step.get('options', [])
            buttons = []
            for opt in options[:3]:  # Max 3 buttons
                btn_id = opt.lower().replace(' ', '_').replace('-', '_')[:20]
                buttons.append({
                    'id': btn_id,
                    'title': opt[:20]
                })
            await wa.send_interactive_buttons(phone, question_text, buttons)
        
        else:
            await wa.send_text(phone, question_text)
    
    def _get_step_by_id(self, flow_config: Dict, step_id: str) -> Optional[Dict]:
        """Find step configuration by ID"""
        steps = flow_config.get('steps', [])
        for step in steps:
            if step.get('id') == step_id:
                return step
        return None
    
    def _get_next_step(self, flow_config: Dict, current_step_id: str, answer_id: str = None) -> str:
        """Determine next step based on current step and answer"""
        current_step = self._get_step_by_id(flow_config, current_step_id)
        if not current_step:
            # If step not found (like 'welcome'), find first real step
            steps = flow_config.get('steps', [])
            if steps:
                return steps[0]['id']
            return 'complete'
        
        next_step = current_step.get('next_step')
        
        # Handle branching logic if present
        if answer_id and 'branches' in current_step:
            branches = current_step['branches']
            if answer_id in branches:
                return branches[answer_id]
        
        return next_step or 'complete'
    
    def _is_contact_step(self, flow_config: Dict, step_id: str) -> bool:
        """Check if step is contact information capture"""
        step = self._get_step_by_id(flow_config, step_id)
        if step:
            return step.get('type') == 'contact'
        return False
    
    def _parse_contact_info(self, message: str) -> Optional[Dict]:
        """Parse 'Name, Phone' format"""
        parts = message.split(',')
        if len(parts) >= 2:
            return {
                'name': parts[0].strip(),
                'phone': parts[1].strip()
            }
        return None
    
    async def _complete_flow(self, phone: str, client: Dict, flow_config: Dict, 
                            responses: Dict, wa: Any):
        """Complete conversation and save lead"""
        # Calculate lead score
        lead_score = self._calculate_score(responses, flow_config.get('scoring_rules', {}))
        
        # Extract name and phone
        name = responses.get('name', {}).get('value', 'Unknown')
        contact_phone = responses.get('phone', {}).get('value', phone)
        
        # Build lead data
        lead_data = {}
        for key, val in responses.items():
            if key not in ['name', 'phone']:
                lead_data[key] = val.get('value', val)
        
        # Save lead
        from database import create_lead, clear_user_session
        lead_id = create_lead(
            client_id=client['id'],
            name=name,
            phone=contact_phone,
            lead_data=lead_data,
            lead_score=lead_score
        )
        
        if lead_id > 0:
            # Send confirmation
            template = flow_config.get('confirmation_template', 
                                      'Thank you {name}. We will contact you soon.')
            confirmation = self._render_template(template, responses, name)
            await wa.send_text(phone, confirmation)
        else:
            await wa.send_text(phone, "Sorry, there was an error saving your information. Please try again.")
        
        # Clear session
        clear_user_session(phone)
    
    def _calculate_score(self, responses: Dict, scoring_rules: Dict) -> int:
        """Calculate lead score based on responses"""
        score = 0
        for question_id, rules in scoring_rules.items():
            response = responses.get(question_id, {})
            answer_value = response.get('value', '')
            if answer_value in rules:
                score += rules[answer_value]
        return min(score, 100)  # Cap at 100
    
    def _render_template(self, template: str, responses: Dict, default_name: str) -> str:
        """Replace placeholders in template with actual values"""
        result = template.replace('{name}', default_name)
        
        for key, val in responses.items():
            if isinstance(val, dict):
                placeholder = '{' + key + '}'
                result = result.replace(placeholder, val.get('value', ''))
            elif isinstance(val, str):
                placeholder = '{' + key + '}'
                result = result.replace(placeholder, val)
        
        return result