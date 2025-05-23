from nltk.stem import PorterStemmer
from collections import defaultdict
from conceptnet.fuseki_comunication import execute_query
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import itertools
import numpy as np
from itertools import combinations

def contextual_choice_of_uses(candidates):

    model = SentenceTransformer('all-MiniLM-L6-v2')
    candidates_ = {obj: candidates[obj] for obj in candidates if len(candidates[obj])>1 } 
    objects_ = list(candidates_.keys())
    # 2. Compute embeddings and similarities
    best_phrases = {}
    for obj in objects_:
        # Create a context-aware version of the object name
        #context_obj = f"Considering the presence of {', '.join(objects)} in the image, the {obj} is most likely used for" 
        context_obj = f"Considering that the image contains {', '.join(objects_)}, they are likely being used together, and the primary function of {obj} in this context is"
        # Encode the object context and candidate phrases
        obj_embedding = model.encode(context_obj)  # Encode the object with its context

        candidate_embeddings = model.encode(candidates_[obj])  # Encode candidate multi-word phrases

        
        # Compute cosine similarity between the object and each candidate
        similarities = cosine_similarity([obj_embedding], candidate_embeddings)[0]
        
        # Find the candidate with the highest similarity
        best_index = similarities.argmax()
        best_phrases[obj] = candidates_[obj][best_index]

    return best_phrases


def contextual_choice_of_places(candidates):

    data_dict = candidates
    # Load a multilingual model capable of handling French
    model = SentenceTransformer('all-MiniLM-L6-v2')

    # 2) Compute embeddings for each candidate in each dictionary entry
    #    We'll store results in parallel structures.
    keys = list(data_dict.keys())  # e.g. ["animals", "vehicles", "misc"]
    embeddings_dict = {}
    for k in keys:
        embeddings = model.encode(data_dict[k], convert_to_numpy=True)
        embeddings_dict[k] = embeddings

    # 3) Define a distance function. Here, we'll use pairwise Euclidean distance
    #    among all chosen embeddings, summed up.
    def pairwise_sum_distance(selected_embeddings):
        """
        Given a list of embeddings (one from each entry),
        returns the sum of pairwise Euclidean distances among them.
        """
        dist_sum = 0.0
        n = len(selected_embeddings)
        for i in range(n):
            for j in range(i+1, n):
                dist_sum += np.linalg.norm(selected_embeddings[i] - selected_embeddings[j])
        return dist_sum

    # 4) Brute force: iterate over every combination (picking one candidate from each list)
    best_combo_indices = None
    best_distance = float('inf')

    # We'll need to keep track of how many candidates each list has:
    list_sizes = [len(data_dict[k]) for k in keys]  # e.g. [3, 3, 3]

    # Now, iterate over the Cartesian product of all candidate indices.
    for combo_indices in itertools.product(*[range(size) for size in list_sizes]):
        # combo_indices might look like (0, 2, 1) meaning:
        # pick data_dict[keys[0]][0], data_dict[keys[1]][2], data_dict[keys[2]][1]
        selected_embeddings = []
        for i, k in enumerate(keys):
            idx = combo_indices[i]
            selected_embeddings.append(embeddings_dict[k][idx])

        # Compute the chosen distance function
        dist_value = pairwise_sum_distance(selected_embeddings)
        if dist_value < best_distance:
            best_distance = dist_value
            best_combo_indices = combo_indices

    # Map the best indices back to the actual words
    best_choices = {}
    for i, k in enumerate(keys):
        best_choices[k] = data_dict[k][best_combo_indices[i]]
    
    return best_choices


def get_graph_data(objects):
    """
    Returns dictionaries for 'used_for', 'is_a', and 'at_location' relations.
    """

    def get_used_for(object_):
        """Query to fetch 'used_for' relations for the given object."""
        query = f"""
        PREFIX concepts: <http://localhost:3030/rcra_project/conceptnet/concept/>
        PREFIX relations: <http://localhost:3030/rcra_project/conceptnet/relation/>
        PREFIX metadata: <http://localhost:3030/rcra_project/conceptnet/metadata/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?object ?weight
        WHERE {{
            concepts:{object_} relations:used_for ?object .
            ?triple rdf:type rdf:Statement .
            ?triple metadata:hasWeight ?weight .
            ?triple rdf:subject concepts:{object_} .
            ?triple rdf:predicate relations:used_for .
            ?triple rdf:object ?object .
        }}
        ORDER BY DESC(?weight)
        """
        return execute_query(query)

    def get_is_a_parent(object_):
        """Query to fetch the 'is_a' parent with the highest weight."""
        query = f"""
        PREFIX concepts: <http://localhost:3030/rcra_project/conceptnet/concept/>
        PREFIX relations: <http://localhost:3030/rcra_project/conceptnet/relation/>
        PREFIX metadata: <http://localhost:3030/rcra_project/conceptnet/metadata/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?parent ?weight
        WHERE {{
            concepts:{object_} relations:is_a ?parent .
            ?triple rdf:type rdf:Statement .
            ?triple metadata:hasWeight ?weight .
            ?triple rdf:subject concepts:{object_} .
            ?triple rdf:predicate relations:is_a .
            ?triple rdf:object ?parent .
        }}
        ORDER BY DESC(?weight)
        LIMIT 1
        """
        result = execute_query(query)
        return result[0] if result else None

    def get_at_location(object_):
        """Query to fetch 'at_location' relations for the given object."""
        query = f"""
        PREFIX concepts: <http://localhost:3030/rcra_project/conceptnet/concept/>
        PREFIX relations: <http://localhost:3030/rcra_project/conceptnet/relation/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?location
        WHERE {{
            concepts:{object_} relations:at_location ?location .
        }}
        """
        results = execute_query(query)
        return {res['location'] for res in results}

    def get_is_a_parent_with_location(object_):
        """Fetches the 'is_a' parent with the highest weight."""
        query = f"""
        PREFIX concepts: <http://localhost:3030/rcra_project/conceptnet/concept/>
        PREFIX relations: <http://localhost:3030/rcra_project/conceptnet/relation/>
        PREFIX metadata: <http://localhost:3030/rcra_project/conceptnet/metadata/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?parent ?weight
        WHERE {{
            concepts:{object_} relations:is_a ?parent .
            ?triple rdf:type rdf:Statement .
            ?triple metadata:hasWeight ?weight .
            ?triple rdf:subject concepts:{object_} .
            ?triple rdf:predicate relations:is_a .
            ?triple rdf:object ?parent .
        }}
        ORDER BY DESC(?weight)
        """
        results = execute_query(query)
        for res in results:
            parent = res['parent']
            parent_locations = get_at_location(parent)
            if parent_locations:
                return {'parent': parent, 'weight': float(res['weight']), 'locations': parent_locations}
        return None

    # Step 1: Initialize maps for relations
    used_for_map = defaultdict(list)
    is_a_map = defaultdict(list)
    at_location_map = defaultdict(set)

    # Step 2: Process each object
    for obj in objects:
        # Fetch 'used_for' relations
        results = get_used_for(obj)

        if not results:  # No 'used_for', check 'is_a' parent
            parent_data = get_is_a_parent(obj)
            if parent_data:
                parent = parent_data['parent']
                parent_used_for = get_used_for(parent)
                while not parent_used_for:  # Recursively check parent
                    parent_data = get_is_a_parent(parent)
                    if not parent_data:
                        break
                    parent = parent_data['parent']
                    parent_used_for = get_used_for(parent)
                if parent_used_for:
                    used_for_map[parent].extend([(parent, 'used_for', rel['object'], float(rel['weight'])) for rel in parent_used_for])
                is_a_map[obj].append((obj, 'is_a', parent, float(parent_data['weight'])))
        else:
            used_for_map[obj].extend([(obj, 'used_for', rel['object'], float(rel['weight'])) for rel in results])

        # Fetch 'at_location' relations
        locations = get_at_location(obj)
        if not locations:  # No direct locations, check 'is_a' parent
            parent_data = get_is_a_parent_with_location(obj)
            if parent_data:
                at_location_map[obj].update(parent_data['locations'])
                is_a_map[obj].append((obj, 'is_a', parent_data['parent'], float(parent_data['weight'])))
        else:
            at_location_map[obj].update(locations)

    # Step 3: Process and filter 'used_for'
    used_for_result = defaultdict(list)
    for obj in used_for_map:
        obj_stem = PorterStemmer().stem(obj)
        for tripl in used_for_map[obj]:
            possible_use = " ".join(tripl[2].split("_"))
            take_it = True
            for word in possible_use.split():
                if PorterStemmer().stem(word) == obj_stem:
                    take_it = False
                    break
            if take_it or len(used_for_map[obj]) == 1:
                used_for_result[obj].append(possible_use)

    # Step 4: Extract 'is_a' and 'at_location'
    is_a_result = {obj: [is_a_map[obj][0][-2]] for obj in is_a_map if is_a_map[obj]}
    at_location_result = {obj: list(locations) for obj, locations in at_location_map.items()}
    
    # break the words 
    for k in used_for_result:
        for i,_ in enumerate(used_for_result[k]) :
            
            used_for_result[k][i] = used_for_result[k][i].replace("_", " ")
    
    for k in is_a_result:
        for i,_ in enumerate(is_a_result[k]) :
            is_a_result[k][i] = is_a_result[k][i].replace("_", " ")
    
    for k in at_location_result:
        for i,_ in enumerate(at_location_result[k]) :
            at_location_result[k][i] = at_location_result[k][i].replace("_", " ")
            
            
    used_for_result = contextual_choice_of_uses(used_for_result)
    at_location_result = contextual_choice_of_places(at_location_result)

    return used_for_result, is_a_result, at_location_result


#====== fullly connected graph ======



def get_rel_count(obj):
    """
    Get the number of relations for a given object.
    """
    query = f"""
        PREFIX concepts: <http://localhost:3030/rcra_project/conceptnet/concept/>
        PREFIX relations: <http://localhost:3030/rcra_project/conceptnet/relation/>
        PREFIX metadata: <http://localhost:3030/rcra_project/conceptnet/metadata/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?p (COUNT(?p) AS ?count)
        WHERE {{
            ?r ?p ?o .
            FILTER (?o = concepts:{obj})
        }}
        GROUP BY ?p
    """
    
    results = execute_query(query)
    
    rel_count = {}
    for result in results:
        rel_count[result['p']] = result['count']
    
    return rel_count

def get_super(obj):
    """
    Get the superclasses of a given object.
    """
    query = f"""
        PREFIX concepts: <http://localhost:3030/rcra_project/conceptnet/concept/>
        PREFIX relations: <http://localhost:3030/rcra_project/conceptnet/relation/>
        PREFIX metadata: <http://localhost:3030/rcra_project/conceptnet/metadata/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT ?o
        WHERE {{
            ?r relations:is_a ?o .
            FILTER (?r = concepts:{obj})
        }}
    """
    
    results = execute_query(query)
    
    super_classes = []
    for result in results:
        super_classes.append(result['o'])
    
    return super_classes



def get_common_connections(object1, object2):
  
    objects_list = [object1, object2]
    # Convert Python list into a SPARQL-friendly string of URIs: concepts:pen, concepts:paper, etc.
    items_str = " ".join(f"concepts:{obj}" for obj in objects_list)
    list_size = len(objects_list)  # For checking "common to all items"

    query = f"""
    PREFIX concepts: <http://localhost:3030/rcra_project/conceptnet/concept/>
    PREFIX relations: <http://localhost:3030/rcra_project/conceptnet/relation/>
    PREFIX metadata: <http://localhost:3030/rcra_project/conceptnet/metadata/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

    ##############################################################################
    # We do this in ONE query with a sub-select for (r, t) pairs that appear
    # for *all* items, then we join back in the main query to return each
    # (item, relation, target, weight).
    ##############################################################################
    SELECT ?item ?relation ?target ?weight
    WHERE {{
      
      ##############################################################################
      # 1) SUB-SELECT: find (r, t) that appear for ALL items in `objects_list`.
      #    - We'll call the item variable ?x inside the sub-select.
      #    - We do a COUNT(DISTINCT ?x).
      #    - Then we HAVING(?cnt = list_size) to keep only "common" pairs.
      ##############################################################################
      {{
        SELECT ?r ?t (COUNT(DISTINCT ?x) AS ?cnt)
        WHERE {{
          VALUES ?x {{ {items_str} }}

          # A) direct used_for
          {{
            ?x relations:used_for ?t .
            BIND(relations:used_for AS ?r)
          }}
          UNION
          # B) direct is_a
          {{
            ?x relations:is_a ?t .
            BIND(relations:is_a AS ?r)
          }}
          UNION
          # C) direct at_location
          {{
            ?x relations:at_location ?t .
            BIND(relations:at_location AS ?r)
          }}
          UNION
          # D) fallback at_location (if no direct at_location)
          {{
            FILTER NOT EXISTS {{ ?x relations:at_location ?directLoc. }}
            ?x (relations:is_a)+ ?super .
            ?super relations:at_location ?t .
            BIND(relations:at_location AS ?r)
          }}
        }}
        GROUP BY ?r ?t
        HAVING (?cnt = {list_size})  # keep only pairs that appear for ALL items
      }}

      ##############################################################################
      # 2) MAIN QUERY: now retrieve (item, relation, target, weight) for each
      #    item in the list. We do the same union logic for actual edges, but
      #    we keep only if (relation, target) = (r, t) from the sub-select above.
      ##############################################################################
      VALUES ?item {{ {items_str} }}

      # Union logic: produce ?item, ?relation, ?target, ?weight
      
      # A) direct used_for
      {{
        ?item relations:used_for ?target .
        ?triple rdf:subject ?item ;
                rdf:predicate relations:used_for ;
                rdf:object ?target ;
                metadata:hasWeight ?weight .
        BIND(relations:used_for AS ?relation)
      }}
      UNION
      # B) direct is_a
      {{
        ?item relations:is_a ?target .
        ?triple rdf:subject ?item ;
                rdf:predicate relations:is_a ;
                rdf:object ?target ;
                metadata:hasWeight ?weight .
        BIND(relations:is_a AS ?relation)
      }}
      UNION
      # C) direct at_location
      {{
        ?item relations:at_location ?target .
        ?triple rdf:subject ?item ;
                rdf:predicate relations:at_location ;
                rdf:object ?target ;
                metadata:hasWeight ?weight .
        BIND(relations:at_location AS ?relation)
      }}
      UNION
      # D) fallback at_location
      {{
        FILTER NOT EXISTS {{ ?item relations:at_location ?directLoc2. }}
        ?item (relations:is_a)+ ?super2 .
        ?super2 relations:at_location ?target .
        ?triple rdf:subject ?super2 ;
                rdf:predicate relations:at_location ;
                rdf:object ?target ;
                metadata:hasWeight ?weight .
        BIND(relations:at_location AS ?relation)
      }}

      ##############################################################################
      # 3) Join with sub-select: Keep only rows where (relation, target) == (r, t)
      #    from the sub-select above. If (relation, target) is not "common," it
      #    won't appear in the final result set.
      ##############################################################################
      FILTER(?relation = ?r && ?target = ?t)
      
    }}
    ORDER BY ?item DESC(?weight)
    """
    
    exe_result = execute_query(query)
    result = []
    for r in exe_result:
        result.append((r['item'], r['relation'], r['target']))
    
    while len(result) ==0 :
        # get obj1 parrents
        super_classes = get_super(object1)
        # get obj2 parrents
        super_classes2 = get_super(object2)
        # check the one with the less nb of parrents 
        if len(super_classes) > len(super_classes2):
            result = [(object2, "is_a", super_classes2[0])]
            result.extend(get_common_connections(object1, super_classes2[0]))
            
        else:
            result = [(object1, "is_a", super_classes[0])]
            result.extend(get_common_connections(object2, super_classes[0]))
    return result
  
def get_connected_graph(object_list):
    """
    Get the graph data for a list of objects.
    """
    pairs = combinations(object_list, 2)
    graph = []
    for obj1, obj2 in pairs:
        connections = get_common_connections(obj1, obj2)
        graph.extend(connections)
    return list(set(graph))
