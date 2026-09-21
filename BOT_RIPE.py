import io
import json
import os
import time
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Monitor Shopify - Extracción Completa de Variantes",
    page_icon="🛒",
    layout="wide",
)

ARCHIVO_STORAGE = "productos_conocidos_v8.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# --- ESTADOS DE SESIÓN ---
if "carrito_items" not in st.session_state:
    st.session_state.carrito_items = []
if "log_alertas" not in st.session_state:
    st.session_state.log_alertas = []
if "novedades_visuales" not in st.session_state:
    st.session_state.novedades_visuales = []


# --- FUNCIONES DE APOYO ---
def cargar_estado():
    if os.path.exists(ARCHIVO_STORAGE):
        with open(ARCHIVO_STORAGE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def guardar_estado(estado):
    with open(ARCHIVO_STORAGE, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def callback_agregar_carrito(tienda, producto_titulo, variante_obj):
    st.session_state.carrito_items.append({
        "tienda": tienda,
        "producto": producto_titulo,
        "talla": variante_obj["talla"],
        "variant_id": variante_obj["variant_id"],
        "precio": variante_obj["precio"],
        "cantidad": 1,
    })


def extraer_todas_las_variantes(producto, tienda_url):
    """Extrae ABSOLUTAMENTE TODAS las variantes del JSON de Shopify sin descartar por stock."""
    variantes_procesadas = []
    raw_variants = producto.get("variants", [])
    raw_options = producto.get("options", [])

    for v in raw_variants:
        v_id = str(v.get("id"))
        v_price = float(v.get("price", 0))
        v_available = v.get("available", False)

        # Reconstruir nombre exacto de la variante combinando options
        nombres_opt = []
        for i in range(1, 4):
            val_opt = v.get(f"option{i}")
            if val_opt and str(val_opt).strip() != "Default Title":
                nombres_opt.append(str(val_opt).strip())

        if nombres_opt:
            talla_nombre = " / ".join(nombres_opt)
        else:
            talla_nombre = v.get("title", "Única")

        # Checkout permalink directo
        url_atc_v = f"{tienda_url}/cart/{v_id}:1?checkout=true"

        variantes_procesadas.append({
            "variant_id": v_id,
            "talla": talla_nombre,
            "precio": v_price,
            "disponible": v_available,
            "url_atc": url_atc_v,
        })

    return variantes_procesadas


def obtener_productos_paginados(url_tienda, max_paginas=2):
    """Obtiene productos con paginación para asegurar capturar todo el catálogo."""
    url_limpia = url_tienda.strip().rstrip("/")
    todos_los_productos = []

    for page in range(1, max_paginas + 1):
        endpoint = f"{url_limpia}/products.json?limit=250&page={page}"
        try:
            res = requests.get(endpoint, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                prods = res.json().get("products", [])
                if not prods:
                    break
                todos_los_productos.extend(prods)
            else:
                break
        except Exception:
            break

    return todos_los_productos


# --- INTERFAZ STREAMLIT ---
st.title("🛒 Monitor Shopify Pro (Captura Total de Variantes L, XL, S, M)")

# SIDEBAR CONFIGURACIÓN
st.sidebar.header("⚙️ Configuración")
tiendas_input = st.sidebar.text_area(
    "URLs de Tiendas Shopify (una por línea)",
    "https://www.compraripe.com",
    height=80,
)

intervalo = st.sidebar.slider("Intervalo de revisión (segundos)", 10, 120, 30)
mostrar_sin_stock = st.sidebar.checkbox(
    "Mostrar variantes agotadas en el selector", value=True
)

st.sidebar.subheader("🔍 Filtros")
keywords_input = st.sidebar.text_input("Palabras Clave (separadas por coma)", "")

st.sidebar.subheader("🔔 Notificaciones")
telegram_token = st.sidebar.text_input("Telegram Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Telegram Chat ID")
discord_webhook = st.sidebar.text_input("Discord Webhook URL", type="password")

btn_iniciar = st.sidebar.button("🚀 Iniciar / Actualizar Monitor")

# SIDEBAR CARRITO MULTI-ITEM
st.sidebar.markdown("---")
st.sidebar.header("🛒 Carrito Combinado")

if st.session_state.carrito_items:
    tienda_base = st.session_state.carrito_items[0]["tienda"]
    permalink_parts = []

    for item in st.session_state.carrito_items:
        st.sidebar.caption(
            f"• **{item['producto']}** | Talla: `{item['talla']}` - ${item['precio']}"
        )
        permalink_parts.append(f"{item['variant_id']}:{item['cantidad']}")

    url_checkout_multicart = (
        f"{tienda_base}/cart/{','.join(permalink_parts)}?checkout=true"
    )

    st.sidebar.markdown(
        f"[💳 **IR AL CHECKOUT ({len(st.session_state.carrito_items)} ARTÍCULOS)**]({url_checkout_multicart})"
    )

    if st.sidebar.button("🗑️ Vaciar Carrito"):
        st.session_state.carrito_items = []
        st.rerun()
else:
    st.sidebar.info("Carrito vacío. Selecciona tallas en los productos.")

# PANEL PRINCIPAL
col1, col2, col3 = st.columns(3)
metrica_total = col1.metric("Productos Monitoreados", 0)
metrica_nuevos = col2.metric("Nuevos Detectados", 0)
metrica_modificados = col3.metric("Cambios Detectados", 0)

tab_galeria, tab_alertas, tab_catalogo = st.tabs(
    ["🖼️ Novedades por Talla", "🚨 Alertas en Tiempo Real", "📦 Catálogo General"]
)

with tab_galeria:
    contenedor_galeria = st.container()

with tab_alertas:
    contenedor_alertas = st.empty()

with tab_catalogo:
    contenedor_tabla = st.empty()


def renderizar_novedades():
    with contenedor_galeria:
        if not st.session_state.novedades_visuales:
            st.info("No hay novedades registradas en este ciclo.")
            return

        cols = st.columns(3)
        for idx, item in enumerate(st.session_state.novedades_visuales[:9]):
            with cols[idx % 3]:
                st.image(item["image"], use_container_width=True)
                st.markdown(f"**[{item['title']}]({item['url']})**")
                st.caption(f"Status: {item['type']} | Min: ${item['price']}")

                variantes = item.get("variantes", [])

                if not mostrar_sin_stock:
                    variantes_filtradas = [
                        v for v in variantes if v["disponible"]
                    ]
                else:
                    variantes_filtradas = variantes

                if variantes_filtradas:
                    mapa_variantes = {}
                    for v in variantes_filtradas:
                        estado_str = "✅" if v["disponible"] else "❌ Agotado"
                        key_label = f"{v['talla']} ({estado_str}) - ${v['precio']} [ID:{v['variant_id']}]"
                        mapa_variantes[key_label] = v

                    # ID único combinando el índice del ciclo + URL/Handle del producto
                    prod_uid = item.get("url", "").split("/")[-1] or str(idx)

                    opcion_seleccionada = st.selectbox(
                        "Selecciona Variante/Talla:",
                        list(mapa_variantes.keys()),
                        key=f"sel_var_{idx}_{prod_uid}",  # Key única garantizada
                    )

                    var_obj = mapa_variantes[opcion_seleccionada]

                    col_b1, col_b2 = st.columns(2)

                    col_b1.button(
                        "➕ Carrito",
                        key=f"btn_cart_{idx}_{prod_uid}_{var_obj['variant_id']}",  # Key única para el botón
                        on_click=callback_agregar_carrito,
                        args=(item["tienda"], item["title"], var_obj),
                    )

                    col_b2.markdown(
                        f"[⚡ **Pagar {var_obj['talla']}**]({var_obj['url_atc']})"
                    )
                else:
                    st.error("❌ Sin variantes encontradas")

                st.markdown("---")


renderizar_novedades()


# --- LÓGICA DE MONITOREO ---
if btn_iniciar:
    st.sidebar.success("Monitor Activo 🟢")
    estado_previo = cargar_estado()
    lista_tiendas = [
        t.strip().rstrip("/")
        for t in tiendas_input.split("\n")
        if t.strip()
    ]
    keywords = [
        k.strip().lower() for k in keywords_input.split(",") if k.strip()
    ]

    contador_nuevos = 0
    contador_modificados = 0

    while True:
        productos_totales_ciclo = 0
        lista_tabla = []

        for tienda_url in lista_tiendas:
            productos = obtener_productos_paginados(tienda_url, max_paginas=2)

            if productos:
                productos_totales_ciclo += len(productos)
                estado_nuevo = estado_previo.get(tienda_url, {})

                for prod in productos:
                    prod_id = str(prod["id"])
                    title = prod.get("title", "")
                    handle = prod.get("handle", "")
                    url_prod = f"{tienda_url}/products/{handle}"

                    images = prod.get("images", [])
                    img_src = (
                        images[0].get("src")
                        if images
                        else "https://via.placeholder.com/150"
                    )

                    # EXTRAER TODAS LAS VARIANTES (S, M, L, XL, ETC.)
                    list_variantes = extraer_todas_las_variantes(prod, tienda_url)

                    links_telegram = [
                        f"[{v['talla']}]({v['url_atc']})"
                        for v in list_variantes
                        if v["disponible"]
                    ]

                    precios = [v["precio"] for v in list_variantes]
                    disponibles = [v["disponible"] for v in list_variantes]
                    precio_min = min(precios) if precios else 0
                    hay_stock = any(disponibles)

                    datos_prod_actual = {
                        "title": title,
                        "price": precio_min,
                        "available": hay_stock,
                        "variantes": list_variantes,
                        "url": url_prod,
                        "image": img_src,
                    }

                    lista_tabla.append({
                        "Imagen": img_src,
                        "Tienda": tienda_url,
                        "Producto": title,
                        "Precio Min ($)": precio_min,
                        "Stock": "✅ Si" if hay_stock else "❌ No",
                        "Variantes Totales": len(list_variantes),
                        "Ver Web": url_prod,
                    })

                    # Detección de cambios
                    if estado_nuevo:
                        tipo_alerta = None
                        str_telegram_atc = (
                            " | ".join(links_telegram)
                            if links_telegram
                            else "Agotado"
                        )

                        if prod_id not in estado_nuevo:
                            tipo_alerta = "🚨 NUEVO PRODUCTO"
                            contador_nuevos += 1
                        elif (
                            estado_nuevo[prod_id].get("available") != hay_stock
                        ):
                            estado_str = (
                                "DISPONIBLE" if hay_stock else "AGOTADO"
                            )
                            tipo_alerta = f"🔄 CAMBIO STOCK ({estado_str})"
                            contador_modificados += 1

                        if tipo_alerta:
                            st.session_state.log_alertas.insert(
                                0,
                                {
                                    "Imagen": img_src,
                                    "Tipo": tipo_alerta,
                                    "Hora": time.strftime("%H:%M:%S"),
                                    "Producto": title,
                                    "Precio": f"${precio_min}",
                                    "Ver": url_prod,
                                },
                            )

                            st.session_state.novedades_visuales.insert(
                                0,
                                {
                                    "tienda": tienda_url,
                                    "title": title,
                                    "price": precio_min,
                                    "url": url_prod,
                                    "image": img_src,
                                    "type": tipo_alerta,
                                    "variantes": list_variantes,
                                },
                            )

                    estado_nuevo[prod_id] = datos_prod_actual

                estado_previo[tienda_url] = estado_nuevo

            guardar_estado(estado_previo)

        metrica_total.metric("Productos Monitoreados", productos_totales_ciclo)
        metrica_nuevos.metric("Nuevos Detectados", contador_nuevos)
        metrica_modificados.metric(
            "Cambios Detectados", contador_modificados
        )

        renderizar_novedades()

        if st.session_state.log_alertas:
            df_alertas = pd.DataFrame(st.session_state.log_alertas)
            contenedor_alertas.dataframe(
                df_alertas,
                column_config={
                    "Imagen": st.column_config.ImageColumn("Vista Previa"),
                    "Ver": st.column_config.LinkColumn("Ver Web"),
                },
                use_container_width=True,
            )

        if lista_tabla:
            df_catalogo = pd.DataFrame(lista_tabla)
            contenedor_tabla.dataframe(
                df_catalogo,
                column_config={
                    "Imagen": st.column_config.ImageColumn("Vista Previa"),
                    "Ver Web": st.column_config.LinkColumn("Ir a la Web"),
                },
                use_container_width=True,
            )

        time.sleep(intervalo)