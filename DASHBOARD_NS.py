from flask import Flask, render_template, request, redirect, url_for, jsonify
import xml.etree.ElementTree as ET
import os
import time

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUTA_TDF = os.path.join(BASE_DIR, 'torneo.tdf')

# Diccionarios en memoria para compartir estado global (resultados y reloj)
resultados_ronda = {}
estado_reloj = {
    "tiempo_restante": 30 * 60,
    "tiempo_agotado": False,
    "timestamp_fin": time.time() + (30 * 60)
}

def parsear_tdf():
    if not os.path.exists(RUTA_TDF):
        return {"error": "No hay archivo.", "nombre_torneo": "Dashboard TOM", "jugadores_standings": [], "emparejamientos": [], "ronda_actual": 0, "torneo_finalizado": False}

    try:
        tree = ET.parse(RUTA_TDF)
        root = tree.getroot()

        nombre_torneo_nodo = root.find('data/name')
        if nombre_torneo_nodo is None:
            nombre_torneo_nodo = root.find('.//name')
        nombre_torneo = nombre_torneo_nodo.text if nombre_torneo_nodo is not None else "Torneo Pokémon"

        diccionario_jugadores = {}
        jugadores_drop = set()

        # Extraer jugadores e identificar retiros
        for player in root.findall('players/player'):
            user_id = player.get('userid')
            first_name = player.find('firstname')
            last_name = player.find('lastname')
            
            nombre = ""
            if first_name is not None and first_name.text: nombre += first_name.text + " "
            if last_name is not None and last_name.text: nombre += last_name.text
            
            nombre_completo = nombre.strip()

            if player.find('dropped') is not None:
                jugadores_drop.add(user_id)
                nombre_completo += " (DROP)"

            diccionario_jugadores[user_id] = nombre_completo

        # Extraer Standings y verificar si el torneo ya terminó
        jugadores_standings = []
        torneo_finalizado = False

        for pod in root.findall('standings/pod'):
            # Si existe un pod de standings 'finished', el torneo ha concluido
            if pod.get('type') == 'finished':
                torneo_finalizado = True
                for player_standing in pod.findall('player'):
                    p_id = player_standing.get('id')
                    p_place = player_standing.get('place', '999')
                    
                    if p_id in diccionario_jugadores:
                        jugadores_standings.append({
                            "id": p_id,
                            "nombre": diccionario_jugadores[p_id],
                            "lugar": int(p_place)
                        })
                        
        jugadores_standings = sorted(jugadores_standings, key=lambda x: x['lugar'])

        # Extraer Emparejamientos de la última ronda (solo si el torneo sigue activo)
        emparejamientos_ultima_ronda = []
        ronda_actual = 0

        if not torneo_finalizado:
            todas_las_rondas = root.findall('pods/pod/rounds/round')
            matches_a_procesar = []
            
            for ronda in todas_las_rondas:
                r_num = int(ronda.get('number', 0))
                if r_num > ronda_actual:
                    ronda_actual = r_num
                    matches_a_procesar = ronda.findall('matches/match')
                elif r_num == ronda_actual:
                    matches_a_procesar.extend(ronda.findall('matches/match'))
                    
            for match in matches_a_procesar:
                p1_node = match.find('player1')
                p2_node = match.find('player2')
                single_player_node = match.find('player')
                
                p1_id = p1_node.get('userid') if p1_node is not None else None
                p2_id = p2_node.get('userid') if p2_node is not None else None
                
                if p1_id:
                    p1_nombre = diccionario_jugadores.get(p1_id, "BYE")
                elif single_player_node is not None:
                    p1_id = single_player_node.get('userid')
                    p1_nombre = diccionario_jugadores.get(p1_id, "BYE")
                else:
                    p1_nombre = "BYE"

                p2_nombre = diccionario_jugadores.get(p2_id, "BYE") if p2_id else "BYE"
                
                mesa_nodo = match.find('tablenumber')
                mesa = mesa_nodo.text if mesa_nodo is not None else "0"

                emparejamientos_ultima_ronda.append({
                    "mesa": mesa,
                    "jugador1": p1_nombre,
                    "jugador2": p2_nombre
                })
                
            def ordenar_por_mesa(x):
                try: return int(x['mesa'])
                except: return 999
                    
            emparejamientos_ultima_ronda = sorted(emparejamientos_ultima_ronda, key=ordenar_por_mesa)

        return {
            "error": None,
            "nombre_torneo": nombre_torneo,
            "jugadores_standings": jugadores_standings,
            "emparejamientos": emparejamientos_ultima_ronda,
            "ronda_actual": ronda_actual,
            "torneo_finalizado": torneo_finalizado
        }
    except Exception as e:
        return {"error": f"Error técnico: {e}", "nombre_torneo": "Error", "jugadores_standings": [], "emparejamientos": [], "ronda_actual": 0, "torneo_finalizado": False}

@app.route('/', methods=['GET', 'POST'])
def dashboard():
    error_carga = None
    if request.method == 'POST':
        if 'archivo_tdf' not in request.files:
            return redirect(request.url)
            
        archivo = request.files['archivo_tdf']
        if archivo.filename == '':
            return redirect(request.url)
            
        if archivo and archivo.filename.lower().endswith('.tdf'):
            archivo.save(RUTA_TDF)
            resultados_ronda.clear()
            return redirect(url_for('dashboard'))
        else:
            error_carga = "¡Error! Solo se permiten archivos con extensión .tdf"

    datos = parsear_tdf()
    if error_carga:
        datos['error'] = error_carga

    return render_template('index.html', datos=datos)

@app.route('/guardar_resultado', methods=['POST'])
def guardar_resultado():
    data = request.json
    mesa = str(data.get('mesa'))
    resultado = data.get('resultado') 
    resultados_ronda[mesa] = resultado
    return jsonify({"status": "success"})

@app.route('/obtener_resultados', methods=['GET'])
def obtener_resultados():
    return jsonify(resultados_ronda)

@app.route('/actualizar_reloj', methods=['POST'])
def actualizar_reloj_servidor():
    data = request.json
    estado_reloj["tiempo_restante"] = data.get('tiempo_restante', 1800)
    estado_reloj["tiempo_agotado"] = data.get('tiempo_agotado', False)
    estado_reloj["timestamp_fin"] = time.time() + estado_reloj["tiempo_restante"]
    return jsonify({"status": "success"})

@app.route('/obtener_reloj', methods=['GET'])
def obtener_reloj():
    if not estado_reloj["tiempo_agotado"]:
        restante = int(estado_reloj["timestamp_fin"] - time.time())
        if restante <= 0:
            restante = 0
            estado_reloj["tiempo_agotado"] = True
        estado_reloj["tiempo_restante"] = restante
    
    return jsonify(estado_reloj)

@app.route('/reset', methods=['POST'])
def reset():
    if os.path.exists(RUTA_TDF):
        os.remove(RUTA_TDF)
    resultados_ronda.clear()
    estado_reloj["tiempo_restante"] = 30 * 60
    estado_reloj["tiempo_agotado"] = False
    estado_reloj["timestamp_fin"] = time.time() + (30 * 60)
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=3000)