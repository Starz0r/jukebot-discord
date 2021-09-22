package main

import (
	"sync/atomic"
	"unsafe"
)

// ByteStream is a lock-free, SPSC, queue.
// Taken from: https://www.sobyte.net/post/2021-07/implementing-lock-free-queues-with-go/
type ByteStream struct {
	head unsafe.Pointer
	tail unsafe.Pointer
}
type node struct {
	value int16
	next  unsafe.Pointer
}

// NewByteStream returns an empty stream.
func NewByteStream() *ByteStream {
	n := unsafe.Pointer(&node{})
	return &ByteStream{head: n, tail: n}
}

// Push puts the given value v at the tail of the stream.
func (q *ByteStream) Push(v int16) {
	n := &node{value: v}
	for {
		tail := load(&q.tail)
		next := load(&tail.next)
		if tail == load(&q.tail) { // are tail and next consistent?
			if next == nil {
				if cas(&tail.next, next, n) {
					cas(&q.tail, tail, n) // Enqueue is done.  try to swing tail to the inserted node
					return
				}
			} else { // tail was not pointing to the last node
				// try to swing Tail to the next node
				cas(&q.tail, tail, next)
			}
		}
	}
}

// Pop removes and returns the value at the head of the stream.
// It returns nil if the stream is empty.
func (q *ByteStream) Pop() int16 {
	for {
		head := load(&q.head)
		tail := load(&q.tail)
		next := load(&head.next)
		if head == load(&q.head) { // are head, tail, and next consistent?
			if head == tail { // is queue empty or tail falling behind?
				if next == nil { // is queue empty?
					return 0
				}
				// tail is falling behind.  try to advance it
				cas(&q.tail, tail, next)
			} else {
				// read value before CAS otherwise another dequeue might free the next node
				v := next.value
				if cas(&q.head, head, next) {
					return v // Dequeue is done.  return
				}
			}
		}
	}
}
func load(p *unsafe.Pointer) (n *node) {
	return (*node)(atomic.LoadPointer(p))
}
func cas(p *unsafe.Pointer, old, new *node) (ok bool) {
	return atomic.CompareAndSwapPointer(
		p, unsafe.Pointer(old), unsafe.Pointer(new))
}