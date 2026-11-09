-- =====================================================================
-- Migration 101: Allow STRN & sales_tax_status in update_party_info RPC
-- =====================================================================

create or replace function public.update_party_info(
  p_kind text,
  p_record_id uuid,
  p_updates jsonb
) returns jsonb
language plpgsql security definer set search_path to 'public'
as $$
declare
  v_table text; v_org uuid; v_code text;
  v_allowed constant text[] := array[
    'name','legal_name','tax_number','email','phone','website',
    'notes','credit_limit','payment_terms_days','is_active',
    'strn','sales_tax_status'];
  v_old jsonb; v_new jsonb; v_changes jsonb := '{}'::jsonb;
  v_key text; v_val jsonb; v_txt text;
begin
  if p_kind = 'customer' then v_table := 'customers';
  elsif p_kind = 'supplier' then v_table := 'suppliers';
  else raise exception 'Unknown record type: %', p_kind;
  end if;

  if p_kind = 'customer' then
    select organization_id, customer_code into v_org, v_code
      from public.customers where id = p_record_id;
  else
    select organization_id, supplier_code into v_org, v_code
      from public.suppliers where id = p_record_id;
  end if;
  if v_org is null then raise exception 'Record not found'; end if;

  if not has_org_role(v_org, 2::smallint) then
    raise exception 'Only the owner and administrators can edit % details', p_kind;
  end if;
  if p_updates is null or p_updates = '{}'::jsonb then
    raise exception 'No changes to apply';
  end if;

  execute format('select to_jsonb(t.*) from public.%I t where t.id = %L', v_table, p_record_id)
    into v_old;
  if v_old is null then raise exception 'Record not found'; end if;

  for v_key, v_val in select key, value from jsonb_each(p_updates) loop
    if not (v_key = any(v_allowed)) then
      raise exception 'Field "%" is not editable', v_key;
    end if;
    v_txt := v_val #>> '{}';
    if v_key = 'name' and coalesce(length(trim(v_txt)), 0) < 2 then
      raise exception 'Name must be at least 2 characters';
    end if;
    if v_key = 'email' and v_txt is not null and v_txt <> ''
       and v_txt !~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$' then
      raise exception 'Invalid email address';
    end if;
    if v_key = 'credit_limit' and v_txt is not null and v_txt <> ''
       and v_txt::numeric < 0 then
      raise exception 'Credit limit cannot be negative';
    end if;
    if v_key = 'payment_terms_days' and v_txt is not null and v_txt <> ''
       and v_txt::smallint < 0 then
      raise exception 'Payment terms cannot be negative';
    end if;
    if v_key = 'sales_tax_status' and v_txt is not null and v_txt <> ''
       and v_txt not in ('REGISTERED_ACTIVE', 'REGISTERED_INACTIVE', 'UNREGISTERED') then
      raise exception 'Invalid sales tax status: %', v_txt;
    end if;
    v_changes := jsonb_set(v_changes, array[v_key],
      jsonb_build_object('from', v_old -> v_key, 'to', v_val));
  end loop;

  execute format(
    'update public.%I t set %s, updated_at = now() where t.id = %L returning to_jsonb(t.*)',
    v_table,
    (select string_agg(
       format('%I = %s', key,
         case
           when key = 'credit_limit'
             then case when value #>> '{}' = '' then 'null'
                       else format('%L::numeric', value #>> '{}') end
           when key = 'payment_terms_days'
             then case when value #>> '{}' = '' then 'null'
                       else format('%L::smallint', value #>> '{}') end
           when key = 'is_active' then format('%L::boolean', coalesce(value #>> '{}', 'false'))
           else format('%L', nullif(value #>> '{}', ''))
         end),
       ', ' order by key)
     from jsonb_each(p_updates) where key = any(v_allowed)),
    p_record_id
  ) into v_new;
  if v_new is null then raise exception 'Record not found'; end if;

  insert into public.audit_logs (
    organization_id, user_id, actor_type, action, entity_type, entity_id,
    entity_code, old_values, new_values, description
  ) values (
    v_org, auth.uid(), 'USER', 'UPDATE', p_kind, p_record_id, v_code,
    v_old - 'id' - 'organization_id' - 'created_at' - 'updated_at',
    v_new - 'id' - 'organization_id' - 'created_at' - 'updated_at',
    p_kind || ' info updated — ' || (select count(*) from jsonb_object_keys(v_changes))
      || ' field(s) changed'
  );

  return jsonb_build_object('changes', v_changes, 'record', v_new);
end;
$$;

revoke all on function public.update_party_info(text, uuid, jsonb) from public, anon;
grant execute on function public.update_party_info(text, uuid, jsonb) to authenticated;

