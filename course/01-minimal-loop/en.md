# Lesson 01: Minimal Loop

## Introduction

A loop is one of the most fundamental control structures in programming. It allows you to execute a block of code repeatedly, making it possible to automate repetitive tasks efficiently.

## What is a Loop?

A loop consists of three essential components:
1. **Initialization** - Setting up the starting point
2. **Condition** - Deciding when to continue or stop
3. **Update** - Changing the loop variable each iteration

## Types of Loops

### For Loop
Used when you know the number of iterations in advance.

```python
for i in range(5):
    print(f"Iteration {i}")
```

### While Loop
Used when the number of iterations is not predetermined.

```python
count = 0
while count < 5:
    print(f"Count: {count}")
    count += 1
```

## The Minimal Loop Pattern

The simplest form of a loop can be expressed as:

```
initialize
while condition:
    # do something
    update
```

## Example: Printing Numbers

```python
# Print numbers 1 to 5
for i in range(1, 6):
    print(i)
```

Output:
```
1
2
3
4
5
```

## Key Takeaways

- Loops reduce code duplication
- Always ensure your loop has an exit condition to avoid infinite loops
- The loop variable tracks your position in the iteration
- Choose the right loop type based on your needs

## Practice Exercise

Write a loop that prints the first 10 even numbers.

## Next Lesson

In the next lesson, we will explore nested loops and their applications.