"""Generates a sample DSA course syllabus PDF to use as demo input.
Not part of the app — demo fixture generation only.
"""
from fpdf import FPDF

SYLLABUS = """CS-201 DATA STRUCTURES AND ALGORITHMS
Course Syllabus - Semester Outline

TOPIC 1: FOUNDATIONS OF DATA STRUCTURES
1.1 Complexity Analysis
  CS201.1.1 Analyse the time complexity of an algorithm using Big-O notation.
  CS201.1.2 Compare best-case, average-case and worst-case complexity.
1.2 Arrays and Linked Lists
  CS201.2.1 Implement singly and doubly linked list operations.
  CS201.2.2 Contrast array and linked-list performance for insertion and deletion.

TOPIC 2: LINEAR STRUCTURES
2.1 Stacks and Queues
  CS201.3.1 Implement a stack using arrays and linked lists.
  CS201.3.2 Apply stacks to expression evaluation and recursion unwinding.
  CS201.3.3 Implement circular and priority queues.
  Prerequisite: CS201.2.1

TOPIC 3: TREES
3.1 Binary Trees and Binary Search Trees
  CS201.4.1 Perform inorder, preorder and postorder traversal of a binary tree.
  CS201.4.2 Insert, search and delete nodes in a binary search tree.
  Prerequisite: CS201.2.1
3.2 Balanced Trees
  CS201.5.1 Construct an AVL tree and apply rotations to restore balance.
  CS201.5.2 Construct a B-tree of a given order and perform insertion.
  CS201.5.3 Delete a key from a B-tree and explain the rebalancing process.
  Prerequisite: CS201.4.2

TOPIC 4: HASHING
4.1 Hash Tables
  CS201.6.1 Design a hash function and evaluate its distribution quality.
  CS201.6.2 Resolve collisions using linear probing and quadratic probing.
  CS201.6.3 Resolve collisions using separate chaining.
  CS201.6.4 Implement hard deletion of keys from an open-addressed hash table.
  Prerequisite: CS201.1.1

TOPIC 5: GRAPHS
5.1 Graph Representation and Traversal
  CS201.7.1 Represent a graph using adjacency matrix and adjacency list.
  CS201.7.2 Traverse a graph using breadth-first and depth-first search.
  Prerequisite: CS201.3.3
5.2 Shortest Path and Spanning Trees
  CS201.8.1 Compute single-source shortest paths using Dijkstra's algorithm.
  CS201.8.2 Construct a minimum spanning tree using Kruskal's algorithm.
  Prerequisite: CS201.7.2

TOPIC 6: SORTING ALGORITHMS
6.1 Comparison Sorts
  CS201.9.1 Implement merge sort and analyse its complexity.
  CS201.9.2 Implement quick sort and discuss pivot selection strategies.
  CS201.9.3 Implement heap sort using a binary heap.
  Prerequisite: CS201.1.1

ASSESSMENT
Mid-term examinations: 30 percent
Final examination: 50 percent
Assignments and laboratory work: 20 percent
"""

pdf = FPDF()
pdf.add_page()
pdf.set_font("Helvetica", size=10)
for line in SYLLABUS.split("\n"):
    if not line.strip():
        pdf.ln(3)
        continue
    stripped = line.strip()
    if stripped.startswith("TOPIC") or stripped.startswith("CS-201") or stripped == "ASSESSMENT":
        pdf.set_font("Helvetica", "B", size=11)
    elif stripped[0].isdigit() and stripped[1] == ".":
        pdf.set_font("Helvetica", "B", size=10)
    else:
        pdf.set_font("Helvetica", size=10)
    indent = (len(line) - len(line.lstrip())) * 1.6
    pdf.set_x(pdf.l_margin + indent)
    pdf.multi_cell(0, 5, stripped)

out = r"C:\Users\aliab\AppData\Local\Temp\claude\C--Users-aliab-OneDrive-Desktop-curriculumOS\6f92d6c2-7669-4158-9d8e-61e36d16552a\scratchpad\CS201_DSA_Syllabus.pdf"
pdf.output(out)
print("wrote", out)
