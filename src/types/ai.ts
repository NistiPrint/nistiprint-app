export type ExecutionLog = {
  id: number;
  order_sn: string;
  executed_at: string;
  input_data: any;
  chat_context: any;
  extracted_personalization: any;
  model_result: any;
  status: string;
  error_message?: string;
  user_feedback_id?: number;
  metadata?: any;
};

export type Personalization = {
  id: number;
  shopee_order_sn: string;
  bling_id?: string;
  item_id?: string;
  item_description?: string;
  customization_name?: string;
  customization_initial?: string;
  status: 'SUCCESS' | 'NEEDS_REVIEW' | 'NO_PERSONALIZATION_FOUND';
  reasoning?: string;
  name_source_message_id?: string;
  metadata?: any;
  updated_at: string;
};

export type DashboardOrder = {
  order_sn: string;
  buyer_username: string;
  order_date: string;
  bling_number?: string;
  items_summary?: any;
  has_chat: boolean;
  last_ai_status?: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  from_user_name: string;
  to_user_name: string;
  content: any;
  created_at: string;
  type: string;
};
