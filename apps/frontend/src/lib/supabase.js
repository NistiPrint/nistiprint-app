import { createClient } from '@supabase/supabase-js';

const supabaseUrl = 'https://cfknrplrqvyirjxovuvi.supabase.co';
const supabaseKey = 'sb_publishable_oJzYHMpjC9mQDAFGrAkxPw_41PGArz9';

export const supabase = createClient(supabaseUrl, supabaseKey);
