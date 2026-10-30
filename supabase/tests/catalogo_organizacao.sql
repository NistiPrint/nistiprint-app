BEGIN;
INSERT INTO installed_integrations(id,platform_slug) VALUES(6,'shopee');
INSERT INTO produtos(id,sku,nome,status,tipo_material,categoria_id,estrutura,preco_venda,herdar_bom_pai)
 VALUES(101,'KIT-A','Kit A','ativo','produto_acabado',1,'kit',25,false),
 (102,'KIT-B','Kit B','inativo','produto_acabado',1,'kit',40,false);
INSERT INTO ficha_tecnica(produto_pai_id,componente_id,quantidade_necessaria) VALUES(101,9001,2),(102,9001,3);
INSERT INTO marketplace_anuncios(id,integration_id,item_externo_id,titulo) VALUES(101,6,'external','Kits');
INSERT INTO produto_anuncios(integration_id,item_externo_id,variacao_externa_id,produto_id,anuncio_id,atributos_variacao)
 VALUES(6,'external','a',101,101,'{"Cor":"Azul"}'),(6,'external','b',102,101,'{"Cor":"Rosa"}');
DO $$ DECLARE r jsonb; target integer; BEGIN
 r:=catalogo_organizar_anuncio(101);
 IF r->>'status'<>'created' THEN RAISE EXCEPTION 'Creation failed: %',r; END IF;
 target:=(r->>'produto_pai_id')::integer;
 IF (SELECT count(*) FROM produtos WHERE parent_id=target)<>2 THEN RAISE EXCEPTION 'Missing children'; END IF;
 IF (SELECT preco_venda FROM produtos WHERE id=101)<>25 OR (SELECT status FROM produtos WHERE id=101)<>'ativo'
 OR (SELECT estrutura FROM produtos WHERE id=101)<>'kit' OR (SELECT quantidade_necessaria FROM ficha_tecnica WHERE produto_pai_id=102)<>3 THEN RAISE EXCEPTION 'Operational data changed'; END IF;
 r:=catalogo_organizar_anuncio(101);
 IF r->>'status'<>'unchanged' THEN RAISE EXCEPTION 'Not idempotent: %',r; END IF;
 UPDATE produto_anuncios SET atributos_variacao='{}' WHERE produto_id=102;
 r:=catalogo_organizar_anuncio(101);
 IF r->>'status'<>'pending' THEN RAISE EXCEPTION 'Incomplete attributes accepted'; END IF;
END $$;
ROLLBACK;
